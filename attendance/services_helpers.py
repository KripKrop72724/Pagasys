from datetime import datetime, timedelta, time
from functools import lru_cache
from typing import Iterable, List, Optional, Tuple

from django.db.models import Q
from django.utils import timezone
from django.urls import reverse

from pagasys.models import ShiftRule, _minutes_between

from capture.models import PunchEvent

from .models import AttAdjustment, AttPair


# Canonical pair-level anomaly keys surfaced on AttDay
PAIR_ANOMALY_KEYS = {
    "unpaired_out",
    "missing_out_closed_at_next_in",
    "missing_out",
    "capped",
    "auto_closed",
}


def _close_open_pairs_with_shift(
    pairs: List[AttPair], shift, tz
) -> Tuple[List[AttPair], int, Optional[dict]]:
    """If the last pair is open and a shift is provided, compute closure data.

    Returns the original list of pairs, the number of minutes auto-closed,
    and an anomaly override for the final pair if one is applied. The
    ``AttPair`` instances themselves are not mutated or saved.
    """

    auto_closed = 0
    anomaly_override = None
    if shift and pairs:
        last = pairs[-1]
        if last.out_ts is None and last.in_ts and shift.end_time:
            last_in_ts = last.in_ts.astimezone(tz)
            end_dt = timezone.make_aware(
                datetime.combine(last_in_ts.date(), shift.end_time), tz
            )
            if shift.cross_midnight and end_dt <= last_in_ts:
                end_dt += timedelta(days=1)
            if last_in_ts > end_dt:
                anomaly_override = {
                    **{k: v for k, v in (last.anomaly or {}).items() if k != "missing_out"},
                    "unpaired_out": True,
                }
            elif end_dt > last_in_ts:
                auto_closed = int((end_dt - last_in_ts).total_seconds() // 60)
                anomaly_override = {
                    **{k: v for k, v in (last.anomaly or {}).items() if k != "missing_out"},
                    "auto_closed": True,
                }
    return pairs, auto_closed, anomaly_override


def _collect_pair_anomalies(pairs: List[AttPair]) -> dict:
    """Aggregate per-pair anomalies into canonical day-level counts."""
    merged = {}
    for p in pairs:
        if not p.anomaly:
            continue
        for key, val in p.anomaly.items():
            if key not in PAIR_ANOMALY_KEYS:
                continue
            if isinstance(val, bool):
                if val:
                    merged[key] = merged.get(key, 0) + 1
            else:
                try:
                    merged[key] = merged.get(key, 0) + int(val)
                except (TypeError, ValueError):
                    merged[key] = val
    return merged


def pairs_to_timeline(pairs: Iterable[AttPair]) -> List[Tuple[datetime, datetime]]:
    """Return [(start, end), ...] timeline from AttPairs."""
    tl = []
    for p in pairs:
        if p.in_ts and p.out_ts:
            tl.append((p.in_ts, p.out_ts))
    return tl


@lru_cache(maxsize=None)
def _active_rules_cached(shift_id: int, day: datetime.date) -> dict:
    weekday = day.strftime("%a").upper()[:3]
    qs = (
        ShiftRule.objects.filter(shift_id=shift_id)
        .filter(Q(active_from__isnull=True) | Q(active_from__lte=day))
        .filter(Q(active_to__isnull=True) | Q(active_to__gte=day))
        .filter(Q(weekdays="") | Q(weekdays__icontains=weekday))
    )
    rules = {}
    for r in qs:
        rules.setdefault(r.kind, []).append(r)
    return rules


def active_rules(shift, day: datetime.date) -> dict:
    if not shift:
        return {}
    return _active_rules_cached(shift.id, day)


# expose cache clear for tests
active_rules.cache_clear = _active_rules_cached.cache_clear


def _window_range(day: datetime, window: str, tz):
    start_s, end_s = window.split("-")
    start = timezone.make_aware(
        datetime.combine(day.date(), time.fromisoformat(start_s)), tz
    )
    end = timezone.make_aware(
        datetime.combine(day.date(), time.fromisoformat(end_s)), tz
    )
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _worked_in_range(timeline: List[Tuple[datetime, datetime]], start, end) -> int:
    total = 0
    for s, e in timeline:
        span_start = max(s, start)
        span_end = min(e, end)
        if span_end > span_start:
            total += int((span_end - span_start).total_seconds() // 60)
    return total


def apply_break_rules(
    work_timeline: List[Tuple[datetime, datetime]],
    rules_by_kind: dict,
    day: datetime,
    unpaid_break: int,
    paid_break: int,
    anomalies: dict,
    tz,
):
    """Apply break-related ShiftRules to work timeline."""
    for rule in rules_by_kind.get(ShiftRule.Kind.FIXED_BREAK_WINDOW, []):
        window = rule.value
        params = rule.params or {}
        start, end = _window_range(day, window, tz)
        window_len = int((end - start).total_seconds() // 60)
        worked = _worked_in_range(work_timeline, start, end)
        actual_break = max(0, window_len - worked)
        min_req = int(params.get("min_minutes", 0))
        if actual_break < min_req:
            delta = min_req - actual_break
            if params.get("enforcement") == "auto_deduct":
                if params.get("paid"):
                    paid_break += delta
                else:
                    unpaid_break += delta
                anomalies[f"break_auto_deduct_{rule.id}"] = delta
            else:
                anomalies[f"break_warn_{rule.id}"] = True

    for rule in rules_by_kind.get(ShiftRule.Kind.REQUIRED_BREAK_AFTER_CONSECUTIVE, []):
        params = rule.params or {}
        threshold = int(rule.value)
        req = int(params.get("minutes", 0))
        consecutive = 0
        last_end = None
        for s, e in work_timeline:
            if last_end is not None:
                gap = int((s - last_end).total_seconds() // 60)
                if gap >= req:
                    consecutive = 0
            span = int((e - s).total_seconds() // 60)
            consecutive += span
            if consecutive > threshold:
                if params.get("enforcement") == "auto_deduct":
                    if params.get("paid"):
                        paid_break += req
                    else:
                        unpaid_break += req
                    anomalies[f"break_auto_deduct_{rule.id}"] = req
                else:
                    anomalies[f"break_warn_{rule.id}"] = True
                consecutive = 0
            last_end = e

    for rule in rules_by_kind.get(ShiftRule.Kind.MIN_TOTAL_BREAK_PER_DAY, []):
        params = rule.params or {}
        minimum = int(rule.value)
        current = paid_break if params.get("paid") else unpaid_break
        if current < minimum:
            delta = minimum - current
            if params.get("enforcement") == "auto_deduct":
                if params.get("paid"):
                    paid_break += delta
                else:
                    unpaid_break += delta
                anomalies[f"break_auto_deduct_{rule.id}"] = delta
            else:
                anomalies[f"break_warn_{rule.id}"] = True

    paid_windows = []
    for rule in rules_by_kind.get(ShiftRule.Kind.PAID_BREAK_WINDOW, []):
        paid_windows.append(_window_range(day, rule.value, tz))
    if paid_windows:
        paid_windows.sort()
        merged = []
        cur_s, cur_e = paid_windows[0]
        for s, e in paid_windows[1:]:
            if s <= cur_e:
                if e > cur_e:
                    cur_e = e
            else:
                merged.append((cur_s, cur_e))
                cur_s, cur_e = s, e
        merged.append((cur_s, cur_e))
        for s, e in merged:
            paid_break += _worked_in_range(work_timeline, s, e)

    return unpaid_break, paid_break, anomalies


def ramadan_reduction_minutes(rules_by_kind: dict) -> int:
    """Total minutes reduced by Ramadan rules."""
    total = 0
    for rule in rules_by_kind.get(ShiftRule.Kind.RAMADAN_REDUCE_MINUTES, []):
        try:
            total += int(rule.value)
        except (TypeError, ValueError):
            continue
    return max(0, total)


def scheduled_required_minutes(
    shift, rules_by_kind: dict, leave_portion: float, is_rest: bool
) -> int:
    """Return scheduled required minutes after leave and Ramadan reductions."""
    if not shift or is_rest:
        return 0
    minutes = _minutes_between(
        shift.start_time, shift.end_time, shift.cross_midnight
    ) - (shift.break_minutes or 0)
    minutes -= ramadan_reduction_minutes(rules_by_kind)
    if leave_portion:
        minutes = int(minutes * (1 - leave_portion))
    return max(0, minutes)


def _round_minutes(value: int, rounding: int) -> int:
    if rounding <= 0:
        return value
    remainder = value % rounding
    half = rounding / 2
    if remainder >= half:
        return value + (rounding - remainder)
    return value - remainder


def _minute_in_window(m: int, start: int, end: int) -> bool:
    if end <= start:
        return m >= start or m < end
    return start <= m < end


def classify_ot_minutes(
    work_timeline: List[Tuple[datetime, datetime]],
    night_rules: List[ShiftRule],
    unpaid_break: int,
    scheduled_required_min: int,
    is_holiday: bool,
    cap: Optional[int],
):
    night_windows = []
    for r in night_rules or []:
        try:
            s, e = r.value.split("-")
            start = time.fromisoformat(s)
            end = time.fromisoformat(e)
            night_windows.append((start.hour * 60 + start.minute, end.hour * 60 + end.minute))
        except Exception:
            continue

    regular = 0
    ot_night = 0
    ot_hol = 0
    for s, e in work_timeline:
        cur = s
        while cur < e:
            if is_holiday:
                ot_hol += 1
            else:
                m = cur.hour * 60 + cur.minute
                if any(_minute_in_window(m, ws, we) for ws, we in night_windows):
                    ot_night += 1
                else:
                    regular += 1
            cur += timedelta(minutes=1)

    regular = max(0, regular - unpaid_break)
    ot_reg = max(0, regular - scheduled_required_min)
    work_min = regular - ot_reg

    anomalies = {}
    if cap is not None:
        total = work_min + ot_reg + ot_night + ot_hol
        if total > cap:
            spill = total - cap
            move = min(spill, work_min)
            work_min -= move
            ot_reg += move
            anomalies["overtime_over_cap"] = spill
    return work_min, ot_reg, ot_night, ot_hol, anomalies


def apply_att_adjustments(
    employee_id: int,
    day: datetime.date,
    work_min: int,
    unpaid_break: int,
    paid_break: int,
    ot_reg: int,
    ot_night: int,
    ot_hol: int,
    status: str,
    anomalies: dict,
):
    adjustments = AttAdjustment.objects.filter(employee_id=employee_id, date=day)
    if not adjustments:
        return (
            work_min,
            unpaid_break,
            paid_break,
            ot_reg,
            ot_night,
            ot_hol,
            status,
            anomalies,
            False,
        )

    deltas = {
        "delta_work_min": 0,
        "delta_unpaid_break_min": 0,
        "delta_paid_break_min": 0,
        "delta_ot_regular_min": 0,
        "delta_ot_night_min": 0,
        "delta_ot_holiday_min": 0,
    }
    override = None
    override_applied = False
    for adj in adjustments:
        deltas["delta_work_min"] += adj.delta_work_min
        deltas["delta_unpaid_break_min"] += adj.delta_unpaid_break_min
        deltas["delta_paid_break_min"] += adj.delta_paid_break_min
        deltas["delta_ot_regular_min"] += adj.delta_ot_regular_min
        deltas["delta_ot_night_min"] += adj.delta_ot_night_min
        deltas["delta_ot_holiday_min"] += adj.delta_ot_holiday_min
        if adj.override_status:
            override = adj.override_status

    work_min += deltas["delta_work_min"]
    unpaid_break += deltas["delta_unpaid_break_min"]
    paid_break += deltas["delta_paid_break_min"]
    ot_reg += deltas["delta_ot_regular_min"]
    ot_night += deltas["delta_ot_night_min"]
    ot_hol += deltas["delta_ot_holiday_min"]
    if override:
        status = override
        override_applied = True
    anomalies["manual_adjustments_applied"] = True

    return (
        work_min,
        unpaid_break,
        paid_break,
        ot_reg,
        ot_night,
        ot_hol,
        status,
        anomalies,
        override_applied,
    )


def compute_full_attendance_delta(employee_id: int, day: datetime.date) -> int:
    """Return minutes needed to reach the scheduled requirement for a day.

    Looks up the computed ``AttDay`` record, determines the active shift, and
    returns the positive difference between the scheduled minutes and the
    currently recorded ``work_min``. Raises ``ValueError`` when the prerequisite
    data (attendance day or shift) is missing.
    """

    from .models import AttDay  # imported lazily to avoid circular import

    try:
        att_day = (
            AttDay.objects.select_related("shift", "roster__shift")
            .get(employee_id=employee_id, date=day)
        )
    except AttDay.DoesNotExist as exc:
        raise ValueError(
            "No attendance day found for the employee and date."
        ) from exc

    shift = att_day.shift
    if shift is None and att_day.roster_id:
        shift = att_day.roster.shift
    if shift is None:
        raise ValueError(
            "Assign a shift before marking full attendance for this day."
        )

    rules = active_rules(shift, att_day.date)
    leave_portion = float(att_day.leave_portion or 0)
    required = scheduled_required_minutes(
        shift, rules, leave_portion, att_day.is_rest_day
    )
    missing = required - att_day.work_min
    return max(0, int(missing))


def format_pair_anomalies(anomalies: Optional[dict]) -> List[str]:
    """Return a sorted list of anomaly labels for display."""

    if not anomalies:
        return []
    results: List[str] = []
    for name, value in anomalies.items():
        if isinstance(value, bool):
            if value:
                results.append(name)
        elif value:
            results.append(f"{name}: {value}")
    return sorted(results)


def format_day_anomalies(anomalies: Optional[dict]) -> List[dict]:
    """Canonicalise day-level anomalies into ``[{name, count}, …]``."""

    if not anomalies:
        return []
    items: List[dict] = []
    for name, count in anomalies.items():
        if not count:
            continue
        items.append({"name": name, "count": count, "key": name})
    return sorted(items, key=lambda item: item["name"])


def build_roster_overview(day, *, include_admin_urls: bool = False) -> dict:
    """Summarise roster and shift metadata for an ``AttDay``."""

    employee = getattr(day, "employee", None)
    shift = day.shift or (day.roster.shift if day.roster else None)
    roster = day.roster

    overview = {
        "employee": employee,
        "employee_id": getattr(day, "employee_id", None),
        "employee_display": str(employee) if employee else "",
        "date": day.date,
        "status": day.get_status_display(),
        "status_value": day.status,
        "locked": day.locked,
        "work_min": day.work_min,
        "unpaid_break_min": day.unpaid_break_min,
        "paid_break_min": day.paid_break_min,
        "late_min": day.late_min,
        "early_leave_min": day.early_leave_min,
        "ot_regular_min": day.ot_regular_min,
        "ot_night_min": day.ot_night_min,
        "ot_holiday_min": day.ot_holiday_min,
        "anomalies": format_day_anomalies(getattr(day, "anomalies", None)),
        "is_holiday": day.is_holiday,
        "is_rest_day": day.is_rest_day,
        "on_leave": day.on_leave,
        "leave_portion": day.leave_portion,
    }

    if shift:
        shift_summary = {
            "id": shift.id,
            "name": shift.name,
            "start_time": shift.start_time,
            "end_time": shift.end_time,
            "cross_midnight": shift.cross_midnight,
            "requires_face": shift.requires_face,
            "break_minutes": shift.break_minutes,
            "total_minutes": shift.total_minutes,
        }
        overview["shift"] = shift_summary
        if include_admin_urls:
            overview["shift_admin_url"] = reverse(
                "admin:pagasys_shifttemplate_change", args=[shift.pk]
            )
    else:
        overview["shift"] = None
        if include_admin_urls:
            overview["shift_admin_url"] = None

    if roster:
        roster_summary = {
            "id": roster.id,
            "is_rest_day": roster.is_rest_day,
            "is_holiday": roster.is_holiday,
            "override_start": roster.override_start,
            "override_end": roster.override_end,
        }
        overview["roster"] = roster_summary
        if include_admin_urls:
            overview["roster_admin_url"] = reverse(
                "admin:pagasys_rosterentry_change", args=[roster.pk]
            )
    else:
        overview["roster"] = None
        if include_admin_urls:
            overview["roster_admin_url"] = None

    return overview


def build_pair_sessions(
    day,
    *,
    pair_queryset=None,
    include_admin_urls: bool = False,
) -> List[dict]:
    """Return ordered paired session context for an ``AttDay``."""

    if pair_queryset is None:
        pair_queryset = AttPair.objects.filter(
            employee_id=day.employee_id, date=day.date
        )
    pair_queryset = pair_queryset.order_by("in_ts")

    sessions: List[dict] = []
    for pair in pair_queryset:
        session = {
            "id": pair.id,
            "in_ts": pair.in_ts,
            "out_ts": pair.out_ts,
            "duration_min": pair.duration_min,
            "cross_midnight": pair.cross_midnight,
            "source": pair.get_source_display(),
            "source_value": pair.source,
            "anomalies": format_pair_anomalies(pair.anomaly),
            "in_event_id": pair.in_event_id,
            "out_event_id": pair.out_event_id,
        }
        if include_admin_urls:
            session["admin_url"] = reverse(
                "admin:attendance_attpair_change", args=[pair.pk]
            )
            session["in_event_admin_url"] = (
                reverse("admin:capture_punchevent_change", args=[pair.in_event_id])
                if pair.in_event_id
                else None
            )
            session["out_event_admin_url"] = (
                reverse("admin:capture_punchevent_change", args=[pair.out_event_id])
                if pair.out_event_id
                else None
            )
        sessions.append(session)
    return sessions


def build_punch_events(
    day,
    *,
    punch_queryset=None,
    include_admin_urls: bool = False,
) -> List[dict]:
    """Return ordered punch event context for an ``AttDay``."""

    if punch_queryset is None:
        employee_id = day.employee_id
        punch_queryset = PunchEvent.objects.filter(
            Q(employee_id=employee_id) | Q(matched_employee_id=employee_id)
        )
        punch_queryset = punch_queryset.filter(
            Q(roster_date=day.date) | Q(device_ts__date=day.date)
        )
        employee_company = getattr(getattr(day, "employee", None), "company", None)
        if employee_company:
            punch_queryset = punch_queryset.filter(company_id=employee_company.id)
        punch_queryset = punch_queryset.select_related("device", "exception")
    punch_queryset = punch_queryset.order_by("device_ts")

    punches: List[dict] = []
    for event in punch_queryset:
        device = getattr(event, "device", None)
        exception = getattr(event, "exception", None)
        punch = {
            "id": event.id,
            "device_ts": event.device_ts,
            "server_ts": event.server_ts,
            "action": event.action,
            "device": device,
            "device_id": event.device_id,
            "device_label": str(device) if device else "",
            "face_matched": event.face_matched,
            "requires_face": event.requires_face,
            "geofence_ok": event.geofence_ok,
            "geofence_rule_violation": event.geofence_rule_violation,
            "out_of_scope": event.out_of_scope,
            "roster_fallback": event.roster_fallback,
            "roster_date": event.roster_date,
            "notes": event.notes,
            "exception": (
                {
                    "kind": exception.kind,
                    "details": exception.details,
                }
                if exception
                else None
            ),
        }
        if include_admin_urls:
            punch["admin_url"] = reverse(
                "admin:capture_punchevent_change", args=[event.pk]
            )
        punches.append(punch)
    return punches


def build_adjustments(day, *, adjustment_queryset=None) -> List[AttAdjustment]:
    """Return ordered ``AttAdjustment`` instances for the day."""

    if adjustment_queryset is None:
        adjustment_queryset = AttAdjustment.objects.filter(
            employee_id=day.employee_id, date=day.date
        )
    return list(adjustment_queryset.order_by("created_at", "id"))


def get_day_context(
    day,
    *,
    include_pairs: bool = True,
    include_punches: bool = True,
    include_adjustments: bool = True,
    include_admin_urls: bool = False,
    pair_queryset=None,
    punch_queryset=None,
    adjustment_queryset=None,
) -> dict:
    """Assemble the related context for a computed attendance day."""

    context = {
        "roster_overview": build_roster_overview(
            day, include_admin_urls=include_admin_urls
        )
    }

    if include_pairs:
        context["pair_sessions"] = build_pair_sessions(
            day,
            pair_queryset=pair_queryset,
            include_admin_urls=include_admin_urls,
        )
    else:
        context["pair_sessions"] = []

    if include_punches:
        context["punch_events"] = build_punch_events(
            day,
            punch_queryset=punch_queryset,
            include_admin_urls=include_admin_urls,
        )
    else:
        context["punch_events"] = []

    if include_adjustments:
        context["adjustments"] = build_adjustments(
            day, adjustment_queryset=adjustment_queryset
        )
    else:
        context["adjustments"] = []

    return context
