from rest_framework.permissions import BasePermission
from django.db import models


class IsCompanyMember(BasePermission):
    """Allow access only to users belonging to the company in the URL."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        company_id = view.kwargs.get("company_id")
        if company_id is None:
            return True
        user_company_id = None
        dept = getattr(user, "department", None)
        if dept and getattr(dept, "branch", None):
            user_company_id = dept.branch.company_id
        lic = getattr(user, "trade_license", None)
        if user_company_id is None and lic:
            user_company_id = lic.company_id
        return str(user_company_id) == str(company_id)

class CompanyScopedQuerysetMixin:
    """Restrict queryset to the company inferred from URL or request.user."""

    company_kwarg = "company_id"

    def get_company(self):
        cid = self.kwargs.get(self.company_kwarg)
        if cid is not None:
            from pagasys.models import Company
            return Company.objects.get(pk=cid)
        user = getattr(self.request, "user", None)
        return getattr(user, "company", None)

    def get_queryset(self):
        qs = super().get_queryset()
        company = self.get_company()
        if company is None:
            return qs.none()
        model = qs.model

        if hasattr(model, "company_id"):
            return qs.filter(company=company)
        if model.__name__ == "Holiday":
            return qs.filter(calendar__company=company)
        if model.__name__ == "ShiftRule":
            return qs.filter(shift__company=company)
        if model.__name__ == "RosterEntry":
            return qs.filter(
                models.Q(employee__trade_license__company=company)
                | models.Q(employee__department__branch__company=company)
                | models.Q(employee__project__branch__company=company)
            )
        return qs
