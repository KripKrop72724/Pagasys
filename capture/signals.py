from django.db.models.signals import post_save
from django.dispatch import receiver
from datetime import timedelta

from .models import PunchEvent
from attendance.tasks import pair_employee_day_task, compute_employee_day_task


@receiver(post_save, sender=PunchEvent)
def trigger_compute(sender, instance: PunchEvent, created, **kwargs):
    if not created:
        return
    eid = instance.matched_employee_id
    if not eid:
        return
    d = instance.roster_date or instance.device_ts.date()
    pair_employee_day_task.delay(eid, d.isoformat())
    compute_employee_day_task.delay(eid, d.isoformat())
    compute_employee_day_task.delay(eid, (d - timedelta(days=1)).isoformat())
