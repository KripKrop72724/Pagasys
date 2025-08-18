from __future__ import annotations

from datetime import datetime, time, timedelta, date, timezone as dt_timezone

from celery import shared_task, group, chain
from django.db import transaction, connection, models
from django.utils import timezone

from .models_attendance import (
    AttEvent,
    AttPair,
    RosterEntry,
    ShiftRule,
    ShiftTemplate,
    AttDay,
    LeaveDay,
    Holiday,
)

MAX_DAILY_OT_MINUTES = 120
MAX_PERIOD_OT_MINUTES = 144 * 60


def _lock(company_id: int, employee_id: int, day: date) -> None:
    """Use advisory lock on PostgreSQL, noop elsewhere."""
    if connection.vendor != "postgresql":
        return
    key = hash((company_id, employee_id, int(day.strftime("%Y%m%d")))) & 0x7FFFFFFF
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=dt_timezone.utc) - timedelta(hours=18)
    end = start + timedelta(hours=36, seconds=1)
    return start, end


def _is_ramadan(day: date, company_id: int) -> bool:
    return Holiday.objects.filter(
        calendar__company_id=company_id, date=day, name__icontains="ramadan"
    ).exists()


@shared_task
@transaction.atomic
def pair_events_task(company_id: int, employee_id: int, day: str | date) -> None:
    if isinstance(day, str):
        day = date.fromisoformat(day)

    _lock(company_id, employee_id, day)

    start, end = _day_bounds(day)

    AttPair.objects.filter(
        employee_id=employee_id, in_ts__gte=start, in_ts__lt=end, source="auto"
    ).delete()

    events = list(
        AttEvent.objects
        .filter(company_id=company_id, employee_id=employee_id, ts__gte=start, ts__lt=end)
        .order_by("ts")
    )
    existing_pairs = AttPair.objects.filter(
        employee_id=employee_id, in_ts__gte=start, in_ts__lt=end
    )
    existing_ins = set(existing_pairs.values_list("in_event_id", flat=True))
    existing_outs = set(existing_pairs.values_list("out_event_id", flat=True))

    current_in = None
    seen_in_ts = set()
    to_create: list[AttPair] = []

    for ev in events:
        if ev.id in existing_ins or ev.id in existing_outs:
            continue
        if ev.direction == "IN":
            if ev.ts in seen_in_ts and current_in is not None:
                to_create.append(
                    AttPair(
                        employee_id=employee_id,
                        in_event=current_in,
                        in_ts=current_in.ts,
                        out_event=None,
                        out_ts=None,
                        duration_min=0,
                        source="auto",
                        quality="dup_in",
                    )
                )
                continue
            seen_in_ts.add(ev.ts)
            if current_in is not None:
                to_create.append(
                    AttPair(
                        employee_id=employee_id,
                        in_event=current_in,
                        in_ts=current_in.ts,
                        out_event=None,
                        out_ts=None,
                        duration_min=0,
                        source="auto",
                        quality="missing_out",
                    )
                )
            current_in = ev

        elif ev.direction == "OUT":
            if current_in is None:
                continue
            delta = ev.ts - current_in.ts
            if delta.total_seconds() <= 16 * 3600:
                to_create.append(
                    AttPair(
                        employee_id=employee_id,
                        in_event=current_in,
                        in_ts=current_in.ts,
                        out_event=ev,
                        out_ts=ev.ts,
                        duration_min=int(delta.total_seconds() // 60),
                        source="auto",
                        quality="ok",
                    )
                )
            else:
                to_create.append(
                    AttPair(
                        employee_id=employee_id,
                        in_event=current_in,
                        in_ts=current_in.ts,
                        out_event=None,
                        out_ts=None,
                        duration_min=0,
                        source="auto",
                        quality="missing_out",
                    )
                )
            current_in = None

    if current_in is not None:
        to_create.append(
            AttPair(
                employee_id=employee_id,
                in_event=current_in,
                in_ts=current_in.ts,
                out_event=None,
                out_ts=None,
                duration_min=0,
                source="auto",
                quality="missing_out",
            )
        )

    if to_create:
        AttPair.objects.bulk_create(to_create, batch_size=1000)


@shared_task
@transaction.atomic
def compute_attday_task(company_id: int, employee_id: int, day: str | date) -> None:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    _lock(company_id, employee_id, day)

    roster = (
        RosterEntry.objects.select_related("shift")
        .filter(employee_id=employee_id, date=day)
        .first()
    )
    shift = roster.shift if roster else None
    shift_date = roster.date if roster else day
    if shift is None:
        prev = (
            RosterEntry.objects.select_related("shift")
            .filter(employee_id=employee_id, date=day - timedelta(days=1))
            .first()
        )
        if prev and prev.shift.cross_midnight:
            shift = prev.shift
            shift_date = prev.date

    start_dt = end_dt = None
    break_min = grace_in = grace_out = 0
    rounding = 1
    scheduled_minutes = 0
    if shift:
        start_dt = datetime.combine(shift_date, shift.start_time, tzinfo=dt_timezone.utc)
        end_date = shift_date + timedelta(days=1) if shift.cross_midnight else shift_date
        end_dt = datetime.combine(end_date, shift.end_time, tzinfo=dt_timezone.utc)
        break_min = getattr(shift, "break_minutes", 0)
        grace_in = getattr(shift, "grace_in_min", 0)
        grace_out = getattr(shift, "grace_out_min", 0)
        rounding = max(1, getattr(shift, "rounding_min", 1))
        scheduled_minutes = int((end_dt - start_dt).total_seconds() // 60) - break_min

    reduce_rule = ShiftRule.objects.filter(
        shift=shift, kind="ramadan_reduce_minutes"
    ).first()
    is_holiday = Holiday.objects.filter(
        calendar__company_id=company_id, date=day
    ).exclude(name__icontains="ramadan").exists()
    if shift and reduce_rule and _is_ramadan(day, company_id):
        reduce = int(reduce_rule.value)
        scheduled_minutes = max(0, scheduled_minutes - reduce)
        if end_dt:
            end_dt -= timedelta(minutes=reduce)

    leave_day = (
        LeaveDay.objects.filter(
            request__employee_id=employee_id, date=day, request__status="approved"
        ).first()
    )
    full_day_leave = False
    if shift and leave_day:
        if leave_day.minutes_covered >= scheduled_minutes:
            full_day_leave = True
            scheduled_minutes = 0
        else:
            scheduled_minutes = max(0, scheduled_minutes - leave_day.minutes_covered)
            if end_dt:
                end_dt -= timedelta(minutes=leave_day.minutes_covered)

    pairs = []
    if shift and start_dt and end_dt:
        pairs = list(
            AttPair.objects.filter(
                employee_id=employee_id,
                in_ts__gte=start_dt - timedelta(hours=1),
                in_ts__lt=end_dt + timedelta(hours=1),
            )
        )
    work = max(0, sum(p.duration_min for p in pairs) - break_min)
    if rounding:
        work = (work // rounding) * rounding
    first_in = min((p.in_ts for p in pairs), default=None)
    last_out = max((p.out_ts for p in pairs if p.out_ts), default=None)

    late = 0
    early = 0
    if shift and first_in:
        expected_start = start_dt + timedelta(minutes=grace_in)
        if first_in > expected_start:
            late = int((first_in - expected_start).total_seconds() // 60)
    if shift and last_out and end_dt:
        expected_end = end_dt - timedelta(minutes=grace_out)
        if last_out < expected_end:
            early = int((expected_end - last_out).total_seconds() // 60)

    status = "rest"
    if is_holiday:
        status = "holiday"
    elif full_day_leave:
        status = "leave"
    elif leave_day:
        status = "partial"
    elif shift and work > 0:
        status = "present"
    elif shift:
        status = "absent"

    ot125 = ot150 = 0
    if is_holiday:
        ot150 = work
    elif work > scheduled_minutes:
        ot125 = work - scheduled_minutes

    ot150_night = 0
    if not is_holiday and shift:
        night_start = time(22, 0)
        night_end = time(4, 0)
        shift_exempt = getattr(shift, "shift_worker_night_exempt", False)
        if not shift_exempt and pairs:
            for p in pairs:
                s = p.in_ts
                e = p.out_ts or p.in_ts
                cur = s
                while cur < e:
                    t = cur.time()
                    if night_start <= night_end:
                        in_night = night_start <= t < night_end
                    else:
                        in_night = (t >= night_start) or (t < night_end)
                    if in_night:
                        ot150_night += 1
                    cur += timedelta(minutes=1)
        if ot150_night:
            ot150 += ot150_night
            ot125 = max(0, ot125 - ot150_night)

    notes: dict[str, str] = {}
    if ot125 + ot150 > MAX_DAILY_OT_MINUTES:
        notes["ot_cap"] = "daily limit exceeded"
        total = ot125 + ot150
        if ot150 >= MAX_DAILY_OT_MINUTES:
            ot150 = MAX_DAILY_OT_MINUTES
            ot125 = 0
        else:
            ot125 = MAX_DAILY_OT_MINUTES - ot150

    period_start = day - timedelta(days=20)
    agg = AttDay.objects.filter(
        employee_id=employee_id, date__gte=period_start, date__lt=day
    ).aggregate(s1=models.Sum("ot125_minutes"), s2=models.Sum("ot150_minutes"))
    past_ot = (agg["s1"] or 0) + (agg["s2"] or 0)
    new_total = past_ot + ot125 + ot150
    if new_total > MAX_PERIOD_OT_MINUTES:
        notes["ot_cap_period"] = "3-week limit exceeded"
        excess = new_total - MAX_PERIOD_OT_MINUTES
        if ot125 >= excess:
            ot125 -= excess
        else:
            excess -= ot125
            ot125 = 0
            ot150 = max(0, ot150 - excess)

    day_obj, _ = AttDay.objects.select_for_update().get_or_create(
        employee_id=employee_id, date=day
    )
    if day_obj.locked:
        return
    day_obj.status = status
    day_obj.shift = shift
    day_obj.work_minutes = work
    day_obj.late_minutes = late
    day_obj.early_leave_minutes = early
    day_obj.ot125_minutes = ot125
    day_obj.ot150_minutes = ot150
    day_obj.notes = notes
    day_obj.save()


@shared_task
def recompute_range_task(
    company_id: int, employee_id: int, date_from: str, date_to: str
) -> None:
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)
    jobs = []
    cur = start
    while cur <= end:
        jobs.append(
            chain(
                pair_events_task.si(company_id, employee_id, cur.isoformat()),
                compute_attday_task.si(company_id, employee_id, cur.isoformat()),
            )
        )
        cur += timedelta(days=1)
    if jobs:
        group(jobs).delay()
