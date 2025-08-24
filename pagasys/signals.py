from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_save,
)
from django.dispatch import receiver

from .models import Branch, Holiday, HolidayAuditLog, TradeLicense
from .tasks import recalc_holiday_roster_entries


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
