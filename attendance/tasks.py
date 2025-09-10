from celery import shared_task
from datetime import date, timedelta
from django.utils import timezone
from django.utils.timezone import localdate

from .services import build_pairs_for, compute_att_day


@shared_task(
    bind=True,
    queue="compute",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def pair_employee_day_task(self, employee_id: int, day_iso: str):
    """Build AttPair records for a given employee/day with retry semantics."""
    d = date.fromisoformat(day_iso)
    return build_pairs_for(employee_id, d)


@shared_task(
    bind=True,
    queue="compute",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def compute_employee_day_task(self, employee_id: int, day_iso: str):
    """Compute AttDay aggregates for an employee/day with retry semantics."""
    d = date.fromisoformat(day_iso)
    return compute_att_day(employee_id, d)


@shared_task(
    bind=True,
    queue="compute",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
)
def recompute_range_task(self, employee_ids: list, start_iso: str, end_iso: str):
    """Rebuild pairs and recompute days for a range with retry semantics."""
    s = date.fromisoformat(start_iso)
    e = date.fromisoformat(end_iso)
    cur = s
    total = 0
    while cur <= e:
        for eid in employee_ids:
            build_pairs_for(eid, cur)
            total += compute_att_day(eid, cur)
        cur += timedelta(days=1)
    return total


@shared_task(queue="compute")
def recompute_yesterday_task():
    from pagasys.models import Employee

    yesterday = localdate() - timedelta(days=1)
    eids = list(
        Employee.objects.filter(is_active=True).values_list("id", flat=True)
    )
    if not eids:
        return 0
    return recompute_range_task(
        eids, yesterday.isoformat(), yesterday.isoformat()
    )


@shared_task(queue="compute")
def recompute_recent_task(minutes: int = 5) -> int:
    """Process punches from the last ``minutes`` and recompute affected days."""
    from capture.models import PunchEvent

    cutoff = timezone.now() - timedelta(minutes=minutes)
    qs = (
        PunchEvent.objects.filter(
            device_ts__gte=cutoff, matched_employee_id__isnull=False
        )
        .values_list("matched_employee_id", "roster_date")
        .distinct()
    )
    total = 0
    for eid, day in qs:
        day = day or localdate()
        build_pairs_for(eid, day)
        total += compute_att_day(eid, day)
    return total
