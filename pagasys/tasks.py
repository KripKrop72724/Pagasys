from datetime import date
from typing import Iterable

from celery import shared_task

from .models import RosterEntry, WorkCalendar, effective_calendar_for, holiday_flags


@shared_task
def recalc_holiday_roster_entries(calendar_id: int, dates: Iterable[str]) -> int:
    """Recompute holiday flags for roster entries.

    ``dates`` should be an iterable of ISO-format date strings. Returns the
    number of entries updated.
    """

    cal = WorkCalendar.objects.filter(id=calendar_id).first()
    if not cal:
        return 0
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
        entry.is_holiday, entry.was_holiday = holiday_flags(entry.employee, entry.date, override)
        updated.append(entry)
    if updated:
        RosterEntry.objects.bulk_update(updated, ["is_holiday", "was_holiday"])
    return len(updated)
