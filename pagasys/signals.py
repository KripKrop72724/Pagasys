from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import Branch, TradeLicense


@receiver(m2m_changed, sender=TradeLicense.branches.through)
def enforce_license_branch_company(sender, instance: TradeLicense, action, pk_set, **kwargs):
    if action in {"pre_add", "pre_set"} and pk_set:
        branches = Branch.objects.filter(pk__in=pk_set).only("id", "company_id")
        bad = [b.id for b in branches if b.company_id != instance.company_id]
        if bad:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                "All branches on a license must belong to the license's company."
            )
