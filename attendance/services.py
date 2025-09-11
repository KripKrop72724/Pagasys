from datetime import datetime, date, time
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from capture.models import PunchEvent, PunchException
from .models import AttPair, AttDay, LeaveDay
from pagasys.models import RosterEntry, ShiftRule
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


@transaction.atomic
def build_pairs_for(employee_id: int, day: date, shift=None, tz=None) -> int:
    """Construct AttPair records for an employee/day if not locked."""
    if AttDay.objects.filter(employee_id=employee_id, date=day, locked=True).exists():
        return 0
    roster = (
        RosterEntry.objects.select_related(
            "shift__company", "employee__trade_license__company"
        )
        .filter(employee_id=employee_id, date=day)
        .first()
    )
    if shift is None:
        shift = roster.shift if roster else None
    if tz is None:
        if shift and getattr(shift, "company", None):
            tz_str = shift.company.timezone
        else:
            company = (
                roster.employee.trade_license.company
                if roster and getattr(roster.employee, "trade_license", None)
                else None
            )
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
    for ev, warn in events:
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
    if open_in:
        pairs.append((open_in, None, 0, {"missing_out": True}))

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
                cross_midnight=bool(
                    pin and pout and (pout.local_ts.date() != pin.local_ts.date())
                ),
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
            "employee__trade_license__company",
        )
        .filter(employee_id=employee_id, date=day)
        .first()
    )
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
    company = (
        roster.employee.trade_license.company
        if roster and getattr(roster.employee, "trade_license", None)
        else None
    )
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
        first_in = next((p.in_ts for p in pairs if p.in_ts), None)
        last_out = next((p.out_ts for p in reversed(pairs) if p.out_ts), None)
        if first_in:
            first_in = first_in.astimezone(tz)
            sched_start = timezone.make_aware(datetime.combine(day, shift.start_time), tz)
            grace = timezone.timedelta(minutes=shift.grace_in_min or 0)
            late = (first_in - sched_start - grace).total_seconds() // 60
            late_min = max(0, int(late))
            if shift.late_after_min:
                late_min = max(0, late_min - max(0, shift.late_after_min - shift.grace_in_min))
        if last_out:
            last_out = last_out.astimezone(tz)
            sched_end = timezone.make_aware(datetime.combine(day, shift.end_time), tz)
            if shift.cross_midnight:
                sched_end += timezone.timedelta(days=1)
            if reduction_min:
                sched_end -= timezone.timedelta(minutes=reduction_min)
            grace = timezone.timedelta(minutes=shift.grace_out_min or 0)
            early = (sched_end - last_out - grace).total_seconds() // 60
            early_min = max(0, int(early))
            if shift.early_leave_before_min:
                early_min = max(0, early_min - max(0, shift.early_leave_before_min - shift.grace_out_min))

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
    if on_leave and leave_portion >= 1:
        status = "leave"
    elif is_hol and total_work == 0:
        status = "holiday"
    elif is_rest and total_work == 0:
        status = "rest"
    elif sched_req > 0 and total_work >= sched_req:
        status = "present" if not on_leave else "partial"
    elif total_work > 0 or (on_leave and leave_portion > 0):
        status = "partial"
    else:
        status = "leave" if on_leave else "absent"

    work_min, unpaid_break, paid_break, ot_reg, ot_night, ot_hol, status, anomalies_all = apply_att_adjustments(
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
