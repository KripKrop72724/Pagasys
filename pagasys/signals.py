from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import Branch, TradeLicense


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
