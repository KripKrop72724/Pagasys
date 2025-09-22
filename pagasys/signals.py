import logging
from itertools import islice

from django.db import transaction
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from attendance.tasks import compute_employee_day_task, pair_employee_day_task

from .models import (
    Branch,
    Holiday,
    HolidayAuditLog,
    RosterEntry,
    ShiftTemplate,
    TradeLicense,
)
from .tasks import recalc_holiday_roster_entries


logger = logging.getLogger(__name__)


_ROSTER_REBUILD_BATCH_SIZE = 500


def _chunked(iterator, size):
    while True:
        chunk = list(islice(iterator, size))
        if not chunk:
            break
        yield chunk


def _dispatch_rebuild_tasks(template_id: int, pairs):
    for employee_id, roster_date in pairs:
        day_iso = roster_date.isoformat()
        try:
            pair_employee_day_task.delay(employee_id, day_iso)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to enqueue pair task for employee %s on %s from template %s",
                employee_id,
                day_iso,
                template_id,
            )
        try:
            compute_employee_day_task.delay(employee_id, day_iso)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to enqueue compute task for employee %s on %s from template %s",
                employee_id,
                day_iso,
                template_id,
            )


def _enqueue_shift_template_rebuild(template_id: int) -> None:
    try:
        qs = (
            RosterEntry.objects.filter(shift_id=template_id)
            .values_list("employee_id", "date")
            .distinct()
        )
        iterator = qs.iterator(chunk_size=_ROSTER_REBUILD_BATCH_SIZE)
        for chunk in _chunked(iterator, _ROSTER_REBUILD_BATCH_SIZE):
            _dispatch_rebuild_tasks(template_id, chunk)
    except Exception:  # pragma: no cover - defensive logging
        logger.exception(
            "Unable to enqueue roster rebuild for shift template %s", template_id
        )


@receiver(post_save, sender=ShiftTemplate)
def trigger_recompute_on_shift_template_update(
    sender, instance: ShiftTemplate, created, **kwargs
):
    if created:
        return

    template_id = instance.pk

    transaction.on_commit(lambda: _enqueue_shift_template_rebuild(template_id))


@receiver(m2m_changed, sender=TradeLicense.branches.through)
def enforce_license_branch_company(sender, instance: TradeLicense, action, pk_set, **kwargs):
    if action in {"pre_add", "pre_set"} and pk_set:
        bad = (
            Branch.objects.filter(pk__in=pk_set)
            .exclude(company_id=instance.company_id)
            .values_list("id", flat=True)
        )
        if bad:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                "All branches on a license must belong to the license's company."
            )


@receiver(pre_save, sender=Holiday)
def stash_old_holiday_date(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_date = sender.objects.get(pk=instance.pk).date
        except sender.DoesNotExist:  # pragma: no cover - safeguard
            instance._old_date = None
    else:
        instance._old_date = None


@receiver(post_save, sender=Holiday)
def handle_holiday_save(sender, instance, created, **kwargs):
    from datetime import date as _date

    old_date = getattr(instance, "_old_date", None)
    current = instance.date if isinstance(instance.date, _date) else _date.fromisoformat(str(instance.date))
    dates = {current}
    if old_date and old_date != current:
        dates.add(old_date)
    recalc_holiday_roster_entries.delay(
        instance.calendar_id, [d.isoformat() for d in dates]
    )
    HolidayAuditLog.objects.create(
        calendar=instance.calendar,
        name=instance.name,
        old_date=old_date if not created else None,
        new_date=current,
        action="created" if created else "updated",
    )


@receiver(post_delete, sender=Holiday)
def handle_holiday_delete(sender, instance, **kwargs):
    from datetime import date as _date

    current = instance.date if isinstance(instance.date, _date) else _date.fromisoformat(str(instance.date))
    recalc_holiday_roster_entries.delay(instance.calendar_id, [current.isoformat()])
    HolidayAuditLog.objects.create(
        calendar=instance.calendar,
        name=instance.name,
        old_date=current,
        action="deleted",
    )
