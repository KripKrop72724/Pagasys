from rest_framework.permissions import BasePermission, SAFE_METHODS
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
        proj = getattr(user, "project", None)
        if user_company_id is None and proj and getattr(proj, "branch", None):
            user_company_id = proj.branch.company_id
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

BRANCH_MANAGER = "Branch Manager"
COMPANY_ADMIN = "Company Admin"
DEPT_MANAGER = "Department Manager"
EMPLOYEE_ROLE = "Employee"
PAYROLL_MANAGER = "Payroll Manager"
PROJECT_MANAGER = "Project Manager"

MANAGER_ROLES = {BRANCH_MANAGER, DEPT_MANAGER, PROJECT_MANAGER}
ADMIN_ROLES = {COMPANY_ADMIN, PAYROLL_MANAGER}

def user_roles(user):
    return set(user.groups.values_list("name", flat=True))

POLICY_WRITE = {
    "WorkCalendar": ADMIN_ROLES,
    "Holiday": ADMIN_ROLES,
    "ShiftTemplate": ADMIN_ROLES,
    "ShiftRule": ADMIN_ROLES,
    "LeaveType": ADMIN_ROLES,
    "RosterEntry": ADMIN_ROLES | MANAGER_ROLES,
}
POLICY_READ = {
    "WorkCalendar": ADMIN_ROLES | MANAGER_ROLES,
    "Holiday": ADMIN_ROLES | MANAGER_ROLES,
    "ShiftTemplate": ADMIN_ROLES | MANAGER_ROLES,
    "ShiftRule": ADMIN_ROLES | MANAGER_ROLES,
    "LeaveType": ADMIN_ROLES | MANAGER_ROLES | {EMPLOYEE_ROLE},
    "RosterEntry": ADMIN_ROLES | MANAGER_ROLES | {EMPLOYEE_ROLE},
}
CUSTOM_ACTION = {
    "import_holidays": ADMIN_ROLES,
    "rules": ADMIN_ROLES | MANAGER_ROLES,
    "preview": ADMIN_ROLES | MANAGER_ROLES,
    "validate": ADMIN_ROLES,
    "bulk_upsert": ADMIN_ROLES | MANAGER_ROLES,
    "summary": ADMIN_ROLES | MANAGER_ROLES,
    "schedule_range": ADMIN_ROLES | MANAGER_ROLES,
}

class ActionRolePermission(BasePermission):
    """Check that the user role is allowed for the action or model."""

    def has_permission(self, request, view):
        roles = user_roles(request.user)
        model = getattr(getattr(view, "queryset", None), "model", None)
        model_name = model.__name__ if model else ""
        action = getattr(view, "action", None)
        if action in CUSTOM_ACTION:
            return bool(roles & CUSTOM_ACTION[action])
        if request.method in SAFE_METHODS:
            return bool(roles & POLICY_READ.get(model_name, set()))
        return bool(roles & POLICY_WRITE.get(model_name, set()))

    def has_object_permission(self, request, view, obj):
        return True
