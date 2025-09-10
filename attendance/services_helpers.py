from datetime import datetime, timedelta, time
from functools import lru_cache
from typing import List, Tuple, Iterable, Optional

from django.db.models import Q
from django.utils import timezone

from pagasys.models import ShiftRule, _minutes_between

from .models import AttPair


# Canonical pair-level anomaly keys surfaced on AttDay
PAIR_ANOMALY_KEYS = {
    "unpaired_out",
    "missing_out_closed_at_next_in",
    "missing_out",
    "capped",
    "auto_closed",
}


def _close_open_pairs_with_shift(
    pairs: List[AttPair], shift
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
            tz = timezone.get_current_timezone()
            end_dt = timezone.make_aware(
                datetime.combine(last.in_ts.date(), shift.end_time), tz
            )
            if shift.cross_midnight and end_dt <= last.in_ts:
                end_dt += timedelta(days=1)
            if last.in_ts > end_dt:
                anomaly_override = {
                    **{k: v for k, v in (last.anomaly or {}).items() if k != "missing_out"},
                    "unpaired_out": True,
                }
            elif end_dt > last.in_ts:
                auto_closed = int((end_dt - last.in_ts).total_seconds() // 60)
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


def _window_range(day: datetime, window: str):
    tz = timezone.get_current_timezone()
    start_s, end_s = window.split("-")
    start = timezone.make_aware(datetime.combine(day.date(), time.fromisoformat(start_s)), tz)
    end = timezone.make_aware(datetime.combine(day.date(), time.fromisoformat(end_s)), tz)
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
):
    """Apply break-related ShiftRules to work timeline."""
    for rule in rules_by_kind.get(ShiftRule.Kind.FIXED_BREAK_WINDOW, []):
        window = rule.value
        params = rule.params or {}
        start, end = _window_range(day, window)
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
        paid_windows.append(_window_range(day, rule.value))
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
    from .models import AttAdjustment

    adjustments = AttAdjustment.objects.filter(employee_id=employee_id, date=day)
    if not adjustments:
        return work_min, unpaid_break, paid_break, ot_reg, ot_night, ot_hol, status, anomalies

    deltas = {
        "delta_work_min": 0,
        "delta_unpaid_break_min": 0,
        "delta_paid_break_min": 0,
        "delta_ot_regular_min": 0,
        "delta_ot_night_min": 0,
        "delta_ot_holiday_min": 0,
    }
    override = None
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
    anomalies["manual_adjustments_applied"] = True

    return work_min, unpaid_break, paid_break, ot_reg, ot_night, ot_hol, status, anomalies
