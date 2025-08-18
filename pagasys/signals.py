from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from celery import chain

from .models_attendance import AttEvent
from .tasks_attendance import pair_events_task, compute_attday_task


@receiver(post_save, sender=AttEvent)
def enqueue_pairing(sender, instance, created, **kwargs):
    if not created:
        return
    day = instance.ts.date().isoformat()
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
        pair_events_task(instance.company_id, instance.employee_id, day)
        compute_attday_task(instance.company_id, instance.employee_id, day)
    else:
        chain(
            pair_events_task.s(instance.company_id, instance.employee_id, day),
            compute_attday_task.s(instance.company_id, instance.employee_id, day),
        ).delay()
