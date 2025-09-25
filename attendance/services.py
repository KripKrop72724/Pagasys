import calendar
from collections import Counter, defaultdict, OrderedDict
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from capture.models import PunchEvent, PunchException
from .models import AttPair, AttDay, LeaveDay, AttAdjustment
from .serializers import AttPairSerializer, AttAdjustmentSerializer
from pagasys.models import Employee, RosterEntry, ShiftRule
from pagasys.utils import scope_queryset
from .services_helpers import (
    _close_open_pairs_with_shift,
    _collect_pair_anomalies,
    _round_minutes,
    active_rules,
    pairs_to_timeline,
    apply_break_rules,
    classify_ot_minutes,
    scheduled_required_minutes,
    ramadan_reduction_minutes,
    apply_att_adjustments,
    PAIR_ANOMALY_KEYS,
)

BLOCKING_KINDS = {"geofence_rule"}
MAX_PAIR_MIN = 16 * 60

# Day-level anomaly keys sourced from rejected punches
REJECTION_KEYS = {
    "face_required_no_match",
    "geofence_rule_violation",
    "outside_scope",
}


LOCKED_DAY_REASON = "Attendance day is locked; adjustments are disabled."
UNASSIGNED_BRANCH_LABEL = "Unassigned"

PDF_DAY_LAYOUTS = {
    31: (16, 15),
    30: (15, 15),
    29: (15, 14),
    28: (14, 14),
}

# Maximum number of day columns that can appear in a single PDF table. The
# layout above covers the normal calendar month lengths, but callers still rely
# on this constant to express the upper bound for assertions.
PDF_DAY_COLUMNS = max(max(layout) for layout in PDF_DAY_LAYOUTS.values())

MONTHLY_STATUS_LEGEND = OrderedDict(
    [
        (
            "present",
            {
                "glyph": "P",
                "css_class": "status-present",
                "label": "Present",
            },
        ),
        (
            "absent",
            {
                "glyph": "A",
                "css_class": "status-absent",
                "label": "Absent / Leave",
            },
        ),
        (
            "rest",
            {
                "glyph": "R",
                "css_class": "status-rest",
                "label": "Rest / Holiday",
            },
        ),
        (
            "partial",
            {
                "glyph": "T",
                "css_class": "status-partial",
                "label": "Partial",
            },
        ),
        (
            "empty",
            {
                "glyph": "-",
                "css_class": "status-empty",
                "label": "No data",
            },
        ),
    ]
)

STATUS_TO_LEGEND = {
    "present": "present",
    "absent": "absent",
    "leave": "absent",
    "rest": "rest",
    "holiday": "rest",
    "partial": "partial",
}


def _resolve_day_status(
    *,
    total_work: int,
    sched_req: int,
    on_leave: bool,
    leave_portion: float,
    is_hol: bool,
    is_rest: bool,
) -> str:
    if on_leave and leave_portion >= 1:
        return "leave"
    if is_hol and total_work == 0:
        return "holiday"
    if is_rest and total_work == 0:
        return "rest"
    if sched_req > 0 and total_work >= sched_req:
        return "present" if not on_leave else "partial"
    if total_work > 0 or (on_leave and leave_portion > 0):
        return "partial"
    return "leave" if on_leave else "absent"


def _eligible(ev: PunchEvent):
    warn = {}
    if ev.geofence_rule_violation:
        return False, {"geofence_rule_violation": True}
    if ev.requires_face and not ev.face_matched:
        return False, {"face_required_no_match": True}
    if ev.out_of_scope:
        return False, {"outside_scope": True}
    if ev.geofence_ok is False:
        warn["geofence"] = "outside"
    if ev.notes:
        warn["notes"] = ev.notes
    return True, warn


def _load_employee_with_company(employee_id: int):
    """Return an employee with assignment-linked companies eager loaded."""

    return (
        Employee.objects.select_related(
            "department__branch__company",
            "project__branch__company",
        )
        .filter(id=employee_id)
        .first()
    )


@transaction.atomic
def build_pairs_for(employee_id: int, day: date, shift=None, tz=None) -> int:
    """Construct AttPair records for an employee/day if not locked."""
    if AttDay.objects.filter(employee_id=employee_id, date=day, locked=True).exists():
        return 0
    roster = (
        RosterEntry.objects.select_related(
            "shift__company",
            "employee__department__branch__company",
            "employee__project__branch__company",
        )
        .filter(employee_id=employee_id, date=day)
        .first()
    )
    employee = roster.employee if roster else _load_employee_with_company(employee_id)
    if shift is None:
        shift = roster.shift if roster else None
    if tz is None:
        if shift and getattr(shift, "company", None):
            tz_str = shift.company.timezone
        else:
            company = employee.company if employee else None
            tz_str = company.timezone if company else None
        tz = ZoneInfo(tz_str) if tz_str else timezone.get_default_timezone()
    rules = active_rules(shift, day)
    min_conf = None
    conf_rules = rules.get(ShiftRule.Kind.FACE_MIN_CONF) if shift else None
    if conf_rules:
        try:
            min_conf = float(conf_rules[0].value)
        except (TypeError, ValueError):
            min_conf = None

    qs = (
        PunchEvent.objects.select_for_update(skip_locked=True)
        .filter(matched_employee_id=employee_id, roster_date=day)
        .order_by("device_ts", "id")
    )
    events = []
    for ev in qs:
        ev.local_ts = ev.device_ts.astimezone(tz)
        if (
            min_conf is not None
            and ev.face_confidence is not None
            and float(ev.face_confidence) < min_conf
        ):
            if ev.face_matched:
                ev.face_matched = False
                ev.save(update_fields=["face_matched"])
        ok, info = _eligible(ev)
        if ok:
            events.append((ev, info))
        else:
            reason = next(iter(info))
            PunchException.objects.get_or_create(
                event=ev, defaults={"kind": reason, "details": {}}
            )
    shift_end_dt = None
    if shift and shift.end_time:
        shift_end_dt = timezone.make_aware(datetime.combine(day, shift.end_time), tz)
        if shift.cross_midnight:
            shift_end_dt += timezone.timedelta(days=1)

    pairs = []
    open_in = None
    prev_ev = None
    for ev, warn in events:
        if prev_ev and ev.action == prev_ev.action:
            diff = int((ev.local_ts - prev_ev.local_ts).total_seconds())
            if diff <= 60:
                PunchException.objects.get_or_create(
                    event=ev,
                    defaults={
                        "kind": "duplicate",
                        "details": {
                            "previous_event_id": prev_ev.id,
                            "diff_seconds": diff,
                        },
                    },
                )
                continue
        if shift_end_dt and ev.action == "in" and ev.local_ts > shift_end_dt:
            pairs.append((ev, ev, 0, {"unpaired_out": True, **warn}))
            continue
        if open_in:
            if ev.action in {"out", "auto"}:
                duration = int((ev.local_ts - open_in.local_ts).total_seconds() // 60)
                if 0 < duration <= MAX_PAIR_MIN:
                    pairs.append((open_in, ev, duration, warn))
                else:
                    duration = max(0, min(duration, MAX_PAIR_MIN))
                    pairs.append((open_in, ev, duration, {"capped": True, **warn}))
                open_in = None
            elif ev.action == "in":
                duration = int((ev.local_ts - open_in.local_ts).total_seconds() // 60)
                duration = max(0, min(duration, MAX_PAIR_MIN))
                pairs.append(
                    (open_in, None, duration, {"missing_out_closed_at_next_in": True})
                )
                open_in = ev
        else:
            if ev.action == "out":
                pairs.append((ev, ev, 0, {"unpaired_out": True, **warn}))
            else:  # in or auto
                open_in = ev
        prev_ev = ev
    if open_in:
        pairs.append((open_in, None, 0, {"missing_out": True}))

    def _is_cross_midnight(pin, pout):
        if not (pin and pout):
            return False
        start = getattr(pin, "device_ts", None)
        end = getattr(pout, "device_ts", None)
        if start and end:
            return end.date() != start.date()
        start_local = getattr(pin, "local_ts", None)
        end_local = getattr(pout, "local_ts", None)
        if start_local and end_local:
            return end_local.date() != start_local.date()
        return False

    saved = 0
    for pin, pout, dur, anomaly in pairs:
        in_id = pin.id if pin else 0
        obj, created = AttPair.objects.update_or_create(
            employee_id=employee_id,
            in_event_id=in_id,
            defaults=dict(
                date=day,
                out_event_id=pout.id if pout else None,
                in_ts=pin.local_ts if pin else None,
                out_ts=pout.local_ts if pout else None,
                duration_min=dur,
                cross_midnight=_is_cross_midnight(pin, pout),
                anomaly=anomaly,
            ),
        )
        if created:
            saved += 1
    return saved


@transaction.atomic
def compute_att_day(employee_id: int, day: date) -> int:
    """Compute the canonical AttDay, skipping locked records."""
    roster = (
        RosterEntry.objects.select_related(
            "shift",
            "employee__work_calendar",
            "employee__department__branch__work_calendar",
            "employee__department__branch__company",
            "employee__project__branch__work_calendar",
            "employee__project__branch__company",
        )
        .filter(employee_id=employee_id, date=day)
        .first()
    )
    employee = roster.employee if roster else _load_employee_with_company(employee_id)
    pairs = list(
        AttPair.objects.filter(employee_id=employee_id, date=day).order_by("in_ts")
    )
    if not roster and not pairs:
        AttDay.objects.filter(employee_id=employee_id, date=day).delete()
        return 0

    obj, _ = AttDay.objects.select_for_update().get_or_create(
        employee_id=employee_id, date=day, defaults={"locked": False}
    )
    if obj.locked:
        return 0

    shift = roster.shift if roster else None
    company = employee.company if employee else None
    if shift and getattr(shift, "company", None):
        tz_str = shift.company.timezone
    else:
        tz_str = company.timezone if company else None
    tz = ZoneInfo(tz_str) if tz_str else timezone.get_default_timezone()

    is_rest = bool(roster and roster.is_rest_day)
    is_hol = bool(roster and roster.is_holiday)

    rules_by_kind = active_rules(shift, day)

    pairs, auto_closed_min, anomaly_override = _close_open_pairs_with_shift(
        pairs, shift, tz
    )

    gross = sum(max(0, p.duration_min) for p in pairs)
    unpaid_break = 0
    paid_break = 0
    late_min = early_min = 0
    anomalies_all = _collect_pair_anomalies(pairs[:-1] if anomaly_override else pairs)
    if anomaly_override:
        for key, val in anomaly_override.items():
            if key not in PAIR_ANOMALY_KEYS:
                continue
            if isinstance(val, bool):
                if val:
                    anomalies_all[key] = anomalies_all.get(key, 0) + 1
            else:
                try:
                    anomalies_all[key] = anomalies_all.get(key, 0) + int(val)
                except (TypeError, ValueError):
                    anomalies_all[key] = val
    if auto_closed_min:
        anomalies_all["auto_close_min"] = auto_closed_min

    rej_qs = PunchException.objects.filter(
        event__matched_employee_id=employee_id,
        event__roster_date=day,
        kind__in=REJECTION_KEYS,
    )
    rej_counts = {k: rej_qs.filter(kind=k).count() for k in REJECTION_KEYS}
    for k, v in rej_counts.items():
        if v:
            anomalies_all[k] = v

    work_timeline = [
        (s.astimezone(tz), e.astimezone(tz)) for s, e in pairs_to_timeline(pairs)
    ]

    ld = LeaveDay.objects.filter(employee_id=employee_id, date=day).first()
    on_leave = bool(ld)
    leave_portion = float(ld.portion) if ld else 0.0

    reduction_min = ramadan_reduction_minutes(rules_by_kind)
    sched_req = scheduled_required_minutes(shift, rules_by_kind, leave_portion, is_rest)

    if shift and shift.break_minutes:
        unpaid_break += shift.break_minutes

    unpaid_break, paid_break, anomalies_all = apply_break_rules(
        work_timeline,
        rules_by_kind,
        datetime.combine(day, time.min),
        unpaid_break,
        paid_break,
        anomalies_all,
        tz,
    )

    if shift and not on_leave:
        first_in = next(
            (
                p.in_ts
                for p in pairs
                if p.in_ts and not bool((p.anomaly or {}).get("unpaired_out"))
            ),
            None,
        )
        last_out = next(
            (
                p.out_ts
                for p in reversed(pairs)
                if p.out_ts and not bool((p.anomaly or {}).get("unpaired_out"))
            ),
            None,
        )
        if first_in:
            first_in = timezone.localtime(first_in, tz)
            sched_start = datetime.combine(day, shift.start_time, tzinfo=tz)
            grace = timezone.timedelta(minutes=shift.grace_in_min or 0)
            late = (first_in - sched_start - grace).total_seconds() // 60
            late_min = max(0, int(late))
            if shift.late_after_min:
                late_min = max(
                    0, late_min - max(0, shift.late_after_min - shift.grace_in_min)
                )
        if last_out:
            last_out = timezone.localtime(last_out, tz)
            sched_end = datetime.combine(day, shift.end_time, tzinfo=tz)
            if shift.cross_midnight:
                sched_end += timezone.timedelta(days=1)
            if reduction_min:
                sched_end -= timezone.timedelta(minutes=reduction_min)
            grace = timezone.timedelta(minutes=shift.grace_out_min or 0)
            early = (sched_end - last_out - grace).total_seconds() // 60
            early_min = max(0, int(early))
            if shift.early_leave_before_min:
                early_min = max(
                    0,
                    early_min
                    - max(0, shift.early_leave_before_min - shift.grace_out_min),
                )

    night_rules = rules_by_kind.get(ShiftRule.Kind.NIGHT_OT_WINDOW, [])
    max_rule = rules_by_kind.get(ShiftRule.Kind.MAX_DAILY_HOURS)
    cap = int(max_rule[0].value) if max_rule else None
    work_min, ot_reg, ot_night, ot_hol, cap_anoms = classify_ot_minutes(
        work_timeline,
        night_rules,
        unpaid_break,
        sched_req,
        is_hol,
        cap,
    )
    anomalies_all.update(cap_anoms)

    if shift and shift.rounding_min:
        work_min = _round_minutes(work_min, shift.rounding_min)
        ot_reg = _round_minutes(ot_reg, shift.rounding_min)
        ot_night = _round_minutes(ot_night, shift.rounding_min)
        ot_hol = _round_minutes(ot_hol, shift.rounding_min)

    total_work = work_min + ot_reg + ot_night + ot_hol
    status = _resolve_day_status(
        total_work=total_work,
        sched_req=sched_req,
        on_leave=on_leave,
        leave_portion=leave_portion,
        is_hol=is_hol,
        is_rest=is_rest,
    )

    (
        work_min,
        unpaid_break,
        paid_break,
        ot_reg,
        ot_night,
        ot_hol,
        status,
        anomalies_all,
        override_applied,
    ) = apply_att_adjustments(
        employee_id,
        day,
        work_min,
        unpaid_break,
        paid_break,
        ot_reg,
        ot_night,
        ot_hol,
        status,
        anomalies_all,
    )

    if not override_applied:
        total_work = work_min + ot_reg + ot_night + ot_hol
        status = _resolve_day_status(
            total_work=total_work,
            sched_req=sched_req,
            on_leave=on_leave,
            leave_portion=leave_portion,
            is_hol=is_hol,
            is_rest=is_rest,
        )

    for k, v in dict(
        shift_id=shift.id if shift else None,
        roster_id=roster.id if roster else None,
        work_min=work_min,
        unpaid_break_min=unpaid_break,
        paid_break_min=paid_break,
        late_min=late_min,
        early_leave_min=early_min,
        ot_regular_min=ot_reg,
        ot_night_min=ot_night,
        ot_holiday_min=ot_hol,
        is_holiday=is_hol,
        is_rest_day=is_rest,
        on_leave=on_leave,
        leave_portion=leave_portion,
        pairs_count=len(pairs),
        punches_used=len(pairs) * 2,
        status=status,
        anomalies=anomalies_all,
    ).items():
        setattr(obj, k, v)
    obj.save()
    return 1


def _resolve_month_range(month):
    """Return the first and last day for a month representation."""

    if isinstance(month, tuple) and len(month) == 2:
        start, end = month
        if not isinstance(start, date) or not isinstance(end, date):
            raise ValueError("Month tuple must contain date objects")
    elif isinstance(month, date):
        start = month.replace(day=1)
        days_in_month = calendar.monthrange(start.year, start.month)[1]
        end = start.replace(day=days_in_month)
    elif isinstance(month, str):
        try:
            year, month_value = month.split("-")
            start = date(int(year), int(month_value), 1)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive guard
            raise ValueError("Expected YYYY-MM formatted string") from exc
        days_in_month = calendar.monthrange(start.year, start.month)[1]
        end = start.replace(day=days_in_month)
    else:  # pragma: no cover - defensive guard
        raise ValueError("Unsupported month type")
    if end < start:  # pragma: no cover - invalid ranges guarded upstream
        raise ValueError("Month end must be on or after start")
    return start, end

def _pdf_day_chunk_sizes(total_days):
    """Return the desired chunk sizes for the monthly PDF grid."""

    if total_days <= 0:
        return []
    layout = list(PDF_DAY_LAYOUTS.get(total_days, ()))
    if layout:
        return layout

    # Fallback for non-standard ranges: keep each table within the maximum
    # allowed columns while distributing the remaining days as evenly as
    # possible.
    sizes = []
    remaining = total_days
    while remaining > 0:
        take = min(PDF_DAY_COLUMNS, remaining)
        sizes.append(take)
        remaining -= take
    return sizes


def _build_pdf_day_chunks(days):
    """Split *days* into slices following the PDF day column layout."""

    total_days = len(days)
    chunk_sizes = _pdf_day_chunk_sizes(total_days)
    if not chunk_sizes:
        return [days]

    chunks = []
    offset = 0
    for size in chunk_sizes:
        if offset >= total_days:
            break
        chunks.append(days[offset : offset + size])
        offset += size
    if offset < total_days:
        chunks.append(days[offset:])
    return chunks


def _legend_key_for_status(status: str | None) -> str:
    if not status:
        return "empty"
    return STATUS_TO_LEGEND.get(status, "empty")


def _cell_classnames(raw_status: str | None, legend_key: str, locked: bool) -> str:
    classes = [MONTHLY_STATUS_LEGEND[legend_key]["css_class"]]
    if raw_status and raw_status not in STATUS_TO_LEGEND:
        classes.append(f"status-{raw_status}")
    if locked:
        classes.append("is-locked")
    return " ".join(classes)


def build_monthly_calendar(
    employees,
    month,
    *,
    user,
    include_pairs=False,
    include_adjustments=False,
    include_anomalies=True,
    stats_only=False,
    status_filters=None,
    locked_filter=None,
    serializer_context=None,
):
    """Aggregate AttDay data into calendar payloads and PDF-friendly groups."""

    status_filters = status_filters or []
    serializer_context = serializer_context or {}
    start, end = _resolve_month_range(month)
    days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

    employees = list(employees)
    employee_ids = [employee.id for employee in employees]

    day_map = defaultdict(dict)
    if employee_ids:
        day_qs = (
            AttDay.objects.filter(employee_id__in=employee_ids, date__range=(start, end))
            .select_related("shift", "roster")
            .order_by("employee_id", "date")
        )
        if user is not None:
            day_qs = scope_queryset(day_qs, user)
        if status_filters:
            day_qs = day_qs.filter(status__in=status_filters)
        if locked_filter is not None:
            day_qs = day_qs.filter(locked=locked_filter)
        for day in day_qs:
            day_map[day.employee_id][day.date] = day

    valid_keys = {
        (emp_id, day_date)
        for emp_id, entries in day_map.items()
        for day_date in entries.keys()
    }

    pairs_data = {}
    if include_pairs and not stats_only and valid_keys:
        pair_qs = AttPair.objects.filter(
            employee_id__in=employee_ids, date__range=(start, end)
        ).order_by("in_ts")
        if user is not None:
            pair_qs = scope_queryset(pair_qs, user)
        valid_dates = {key[1] for key in valid_keys}
        pair_qs = pair_qs.filter(date__in=valid_dates)
        grouped_pairs = defaultdict(list)
        for pair in pair_qs:
            key = (pair.employee_id, pair.date)
            if key in valid_keys:
                grouped_pairs[key].append(pair)
        for key, records in grouped_pairs.items():
            pairs_data[key] = AttPairSerializer(
                records, many=True, context=serializer_context
            ).data

    adjustments_data = {}
    if include_adjustments and not stats_only and valid_keys:
        adjustment_qs = AttAdjustment.objects.filter(
            employee_id__in=employee_ids, date__range=(start, end)
        ).order_by("created_at")
        if user is not None:
            adjustment_qs = scope_queryset(adjustment_qs, user)
        valid_dates = {key[1] for key in valid_keys}
        adjustment_qs = adjustment_qs.filter(date__in=valid_dates)
        grouped_adjustments = defaultdict(list)
        for adjustment in adjustment_qs:
            key = (adjustment.employee_id, adjustment.date)
            if key in valid_keys:
                grouped_adjustments[key].append(adjustment)
        for key, records in grouped_adjustments.items():
            adjustments_data[key] = AttAdjustmentSerializer(
                records, many=True, context=serializer_context
            ).data

    payload_employees = []
    branch_employee_map = defaultdict(list)
    branch_totals = defaultdict(Counter)
    overall_totals = Counter()
    legend_keys = list(MONTHLY_STATUS_LEGEND.keys())
    legend_entries = [
        {"key": key, **MONTHLY_STATUS_LEGEND[key]} for key in legend_keys
    ]

    for employee in employees:
        employee_days = day_map.get(employee.id, {})
        summary_counts = Counter()
        locked_days = 0
        total_ot = 0
        rows = []
        report_rows = []
        report_counts = Counter()

        for current_day in days:
            att_day = employee_days.get(current_day)
            raw_status = att_day.status if att_day else None
            legend_key = _legend_key_for_status(raw_status)
            locked = bool(att_day.locked) if att_day else False

            if att_day:
                summary_counts[raw_status] += 1
                if locked:
                    locked_days += 1
                total_ot += (
                    att_day.ot_regular_min
                    + att_day.ot_night_min
                    + att_day.ot_holiday_min
                )
            report_counts[legend_key] += 1

            if not stats_only:
                key = (employee.id, current_day)
                row = {
                    "date": current_day.isoformat(),
                    "status": raw_status,
                    "locked": locked,
                    "locked_reason": LOCKED_DAY_REASON if locked else None,
                    "metrics": {
                        "work_min": att_day.work_min if att_day else 0,
                        "unpaid_break_min": att_day.unpaid_break_min if att_day else 0,
                        "paid_break_min": att_day.paid_break_min if att_day else 0,
                        "late_min": att_day.late_min if att_day else 0,
                        "early_leave_min": att_day.early_leave_min if att_day else 0,
                        "ot_regular_min": att_day.ot_regular_min if att_day else 0,
                        "ot_night_min": att_day.ot_night_min if att_day else 0,
                        "ot_holiday_min": att_day.ot_holiday_min if att_day else 0,
                        "on_leave": att_day.on_leave if att_day else False,
                        "leave_portion": float(att_day.leave_portion) if att_day else 0.0,
                        "is_holiday": att_day.is_holiday if att_day else False,
                        "is_rest_day": att_day.is_rest_day if att_day else False,
                        "pairs_count": att_day.pairs_count if att_day else 0,
                        "punches_used": att_day.punches_used if att_day else 0,
                    },
                }
                if include_anomalies:
                    row["anomalies"] = att_day.anomalies if att_day else {}
                if include_pairs:
                    row["pairs"] = pairs_data.get(key, [])
                if include_adjustments:
                    row["adjustments"] = adjustments_data.get(key, [])
                rows.append(row)

            report_rows.append(
                {
                    "date": current_day,
                    "iso": current_day.isoformat(),
                    "status": raw_status,
                    "legend_key": legend_key,
                    "glyph": MONTHLY_STATUS_LEGEND[legend_key]["glyph"],
                    "css_class": _cell_classnames(raw_status, legend_key, locked),
                    "locked": locked,
                }
            )

        summary = {
            "present": summary_counts.get("present", 0),
            "absent": summary_counts.get("absent", 0),
            "leave": summary_counts.get("leave", 0),
            "holiday": summary_counts.get("holiday", 0),
            "rest": summary_counts.get("rest", 0),
            "partial": summary_counts.get("partial", 0),
            "locked_days": locked_days,
            "total_ot_min": total_ot,
        }

        branch = None
        if employee.department and employee.department.branch:
            branch = employee.department.branch
        elif employee.project and employee.project.branch:
            branch = employee.project.branch
        branch_name = branch.name if branch else UNASSIGNED_BRANCH_LABEL

        display_name = employee.get_full_name().strip() or employee.username
        metadata = {
            "department": employee.department.name if employee.department else None,
            "project": employee.project.name if employee.project else None,
            "branch": branch_name if branch_name else None,
            "code": employee.username,
        }

        payload_employees.append(
            {
                "id": employee.id,
                "display": display_name,
                "metadata": metadata,
                "rows": [] if stats_only else rows,
                "summary": summary,
            }
        )

        branch_employee_map[branch_name].append(
            {
                "id": employee.id,
                "display": display_name,
                "metadata": metadata,
                "rows": report_rows,
                "counts": {key: report_counts.get(key, 0) for key in legend_keys},
            }
        )
        branch_totals[branch_name].update(report_counts)
        overall_totals.update(report_counts)

    report_days = [
        {
            "date": day,
            "iso": day.isoformat(),
            "day": day.day,
            "weekday": day.strftime("%a"),
        }
        for day in days
    ]
    day_chunks = _build_pdf_day_chunks(report_days)

    branch_sections = OrderedDict()
    for branch_name in sorted(branch_employee_map):
        employees_for_branch = branch_employee_map[branch_name]
        employees_for_branch.sort(key=lambda item: item["display"].casefold())
        totals = branch_totals.get(branch_name, Counter())
        tables = []
        start_index = 0
        for index, day_chunk in enumerate(day_chunks):
            end_index = start_index + len(day_chunk)
            table_employees = []
            for employee in employees_for_branch:
                metadata = employee.get("metadata", {})
                table_employees.append(
                    {
                        "meta": {
                            "display": employee.get("display"),
                            "code": metadata.get("code"),
                            "department": metadata.get("department"),
                            "project": metadata.get("project"),
                        },
                        "cells": employee.get("rows", [])[start_index:end_index],
                    }
                )
            tables.append(
                {
                    "days": day_chunk,
                    "employees": table_employees,
                    "show_meta": index == 0,
                }
            )
            start_index = end_index

        branch_sections[branch_name] = {
            "name": branch_name,
            "employees": employees_for_branch,
            "totals": {key: totals.get(key, 0) for key in legend_keys},
            "legend_totals": [
                {**entry, "count": totals.get(entry["key"], 0)}
                for entry in legend_entries
            ],
            "employee_count": len(employees_for_branch),
            "tables": tables if employees_for_branch else [],
        }

    payload = {
        "month": start.strftime("%Y-%m"),
        "days": [day.isoformat() for day in days],
        "employees": payload_employees,
    }
    report = {
        "month": start.strftime("%Y-%m"),
        "month_label": start.strftime("%B %Y"),
        "days": report_days,
        "day_column_layout": [len(chunk) for chunk in day_chunks],
        "branches": branch_sections,
        "branch_list": list(branch_sections.values()),
        "legend": legend_entries,
        "totals": {key: overall_totals.get(key, 0) for key in legend_keys},
        "legend_totals": [
            {**entry, "count": overall_totals.get(entry["key"], 0)}
            for entry in legend_entries
        ],
        "employee_count": len(payload_employees),
    }

    return {"payload": payload, "report": report}
