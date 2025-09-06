from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from pagasys.models import RosterEntry
from .models import LeaveDay
from .tasks import compute_employee_day_task


@receiver(post_save, sender=RosterEntry)
def trigger_compute_on_roster(sender, instance: RosterEntry, **kwargs):
    transaction.on_commit(
        lambda: compute_employee_day_task.delay(
            instance.employee_id, instance.date.isoformat()
        )
    )


@receiver(post_save, sender=LeaveDay)
def trigger_compute_on_leave(sender, instance: LeaveDay, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: compute_employee_day_task.delay(
                instance.employee_id, instance.date.isoformat()
            )
        )
