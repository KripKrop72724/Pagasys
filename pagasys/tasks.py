from datetime import date, timedelta
from typing import Iterable, Sequence

from celery import shared_task
from django.utils import timezone
from zoneinfo import ZoneInfo
from django.db import transaction

from .models import (
    RosterEntry,
    WorkCalendar,
    ShiftTemplate,
    Employee,
    effective_calendar_for,
    holiday_flags,
)

from attendance.tasks import pair_employee_day_task, compute_employee_day_task


@shared_task
def recalc_holiday_roster_entries(calendar_id: int, dates: Iterable[str]) -> int:
    """Recompute holiday flags for roster entries.

    ``dates`` should be an iterable of ISO-format date strings. Returns the
    number of entries updated.
    """

    cal = WorkCalendar.objects.filter(id=calendar_id).select_related("company").first()
    if not cal:
        return 0
    with timezone.override(ZoneInfo(cal.company.timezone)):
        # Parse ISO strings to date objects
        date_objs = [date.fromisoformat(d) if isinstance(d, str) else d for d in dates]
        qs = (
            RosterEntry.objects
            .filter(date__in=date_objs)
            .select_related(
                "employee",
                "employee__work_calendar",
                "employee__department__branch__work_calendar",
                "employee__department__branch__company",
                "employee__project__branch__work_calendar",
                "employee__project__branch__company",
                "employee__trade_license__company",
            )
        )
        updated = []
        for entry in qs:
            eff = effective_calendar_for(entry.employee)
            if not eff or eff.id != calendar_id:
                continue
            override = entry.is_holiday if entry.is_holiday != entry.was_holiday else None
            entry.is_holiday, entry.was_holiday = holiday_flags(
                entry.employee, entry.date, override
            )
            updated.append(entry)
        if updated:
            RosterEntry.objects.bulk_update(updated, ["is_holiday", "was_holiday"])
        return len(updated)


@shared_task
def schedule_range_bulk(
    employee_ids: Sequence[int],
    shift_id: int,
    start: str,
    end: str,
    rest_weekdays: Sequence[str] | None = None,
) -> int:
    """Bulk create roster entries for multiple employees."""

    shift = ShiftTemplate.objects.filter(id=shift_id).first()
    if not shift:
        return 0
    employees = list(Employee.objects.filter(id__in=list(employee_ids)))
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    rest = set(rest_weekdays or [])
    num_days = (end_date - start_date).days + 1
    entries = []
    touched_pairs: set[tuple[int, date]] = set()
    codes = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    for emp in employees:
        for i in range(num_days):
            current = start_date + timedelta(days=i)
            entry = RosterEntry(
                employee=emp,
                date=current,
                shift=shift,
                is_rest_day=codes[current.weekday()] in rest,
            )
            entry.is_holiday, entry.was_holiday = holiday_flags(emp, current, None)
            entry.full_clean(validate_unique=False)
            entries.append(entry)
            touched_pairs.add((entry.employee_id, current))

    def enqueue_pairs(pairs=touched_pairs):
        for emp_id, day in pairs:
            day_iso = day.isoformat()
            pair_employee_day_task.delay(emp_id, day_iso)
            compute_employee_day_task.delay(emp_id, day_iso)

    if entries:
        with transaction.atomic():
            RosterEntry.objects.bulk_create(
                entries,
                update_conflicts=True,
                update_fields=[
                    "shift",
                    "override_start",
                    "override_end",
                    "is_rest_day",
                    "is_holiday",
                    "was_holiday",
                ],
                unique_fields=["employee", "date"],
            )
            if touched_pairs:
                transaction.on_commit(enqueue_pairs)
    return len(entries)
