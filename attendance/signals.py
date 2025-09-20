from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from pagasys.models import RosterEntry
from .models import LeaveDay, AttAdjustment
from .tasks import compute_employee_day_task, pair_employee_day_task


def _enqueue_roster_rebuild(employee_id: int, day):
    day_iso = day.isoformat()
    pair_employee_day_task.delay(employee_id, day_iso)
    compute_employee_day_task.delay(employee_id, day_iso)


@receiver(post_save, sender=RosterEntry)
def trigger_compute_on_roster(sender, instance: RosterEntry, **kwargs):
    transaction.on_commit(
        lambda: _enqueue_roster_rebuild(instance.employee_id, instance.date)
    )


@receiver(post_delete, sender=RosterEntry)
def trigger_compute_on_roster_delete(sender, instance: RosterEntry, **kwargs):
    transaction.on_commit(
        lambda: _enqueue_roster_rebuild(instance.employee_id, instance.date)
    )


@receiver(post_save, sender=LeaveDay)
def trigger_compute_on_leave(sender, instance: LeaveDay, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: compute_employee_day_task.delay(
                instance.employee_id, instance.date.isoformat()
            )
        )


@receiver(post_save, sender=AttAdjustment)
def trigger_compute_on_adjustment_save(
    sender, instance: AttAdjustment, **kwargs
):
    transaction.on_commit(
        lambda: compute_employee_day_task.delay(
            instance.employee_id, instance.date.isoformat()
        )
    )


@receiver(post_delete, sender=AttAdjustment)
def trigger_compute_on_adjustment_delete(
    sender, instance: AttAdjustment, **kwargs
):
    transaction.on_commit(
        lambda: compute_employee_day_task.delay(
            instance.employee_id, instance.date.isoformat()
        )
    )
