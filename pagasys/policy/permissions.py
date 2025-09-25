import logging

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, SAFE_METHODS

from pagasys.utils import employee_company_q


logger = logging.getLogger(__name__)


class IsCompanyMember(BasePermission):
    """Allow access only to users belonging to the company in the URL."""

    message = "User does not belong to the requested company."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        if user.is_superuser:
            return True
        company_id = view.kwargs.get("company_id")
        if company_id is None:
            return True
        company = getattr(user, "assignment_company", None)
        if company is None:
            self.message = "No department/project assignment available for company scoping."
            identifier = getattr(user, "pk", None) or getattr(user, "username", None) or "unknown"
            logger.warning(
                "Denying company access for user %s due to missing organisational assignment", identifier
            )
            return False
        if str(company.id) != str(company_id):
            self.message = "User does not belong to the requested company."
            return False
        return True

class CompanyScopedQuerysetMixin:
    """Restrict queryset to the company inferred from URL or request.user."""

    company_kwarg = "company_id"

    def get_company(self):
        if not hasattr(self, "_company_cache"):
            cid = self.kwargs.get(self.company_kwarg)
            if cid is not None:
                from pagasys.models import Company

                self._company_cache = Company.objects.get(pk=cid)
            else:
                user = getattr(self.request, "user", None)
                if not (user and user.is_authenticated):
                    raise PermissionDenied("Authentication required to resolve company scope.")
                company = getattr(user, "assignment_company", None)
                if company is None:
                    identifier = getattr(user, "pk", None) or getattr(user, "username", None) or "unknown"
                    logger.warning(
                        "Unable to resolve company for user %s without organisational assignment", identifier
                    )
                    raise PermissionDenied(
                        "No department/project assignment available for company scoping."
                    )
                self._company_cache = company
        return self._company_cache

    def get_queryset(self):
        qs = super().get_queryset()
        company = self.get_company()
        if company is None:
            return qs.none()
        model = qs.model

        from pagasys.models import Holiday, ShiftRule, RosterEntry

        if hasattr(model, "company_id"):
            return qs.filter(company=company)
        if model is Holiday:
            return qs.filter(calendar__company=company)
        if model is ShiftRule:
            return qs.filter(shift__company=company)
        if model is RosterEntry:
            return qs.filter(employee_company_q(company, field_prefix="employee"))
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
    "AttendanceDevice": ADMIN_ROLES | MANAGER_ROLES,
    "PunchEvent": ADMIN_ROLES | MANAGER_ROLES,
}
POLICY_READ = {
    "WorkCalendar": ADMIN_ROLES | MANAGER_ROLES,
    "Holiday": ADMIN_ROLES | MANAGER_ROLES,
    "ShiftTemplate": ADMIN_ROLES | MANAGER_ROLES,
    "ShiftRule": ADMIN_ROLES | MANAGER_ROLES,
    "LeaveType": ADMIN_ROLES | MANAGER_ROLES | {EMPLOYEE_ROLE},
    "RosterEntry": ADMIN_ROLES | MANAGER_ROLES | {EMPLOYEE_ROLE},
    "AttendanceDevice": ADMIN_ROLES | MANAGER_ROLES,
    "PunchEvent": ADMIN_ROLES | MANAGER_ROLES,
}
CUSTOM_ACTION = {
    "import_holidays": ADMIN_ROLES,
    "rules": ADMIN_ROLES | MANAGER_ROLES,
    "preview": ADMIN_ROLES | MANAGER_ROLES,
    "validate": ADMIN_ROLES,
    "bulk_upsert": ADMIN_ROLES | MANAGER_ROLES,
    "summary": ADMIN_ROLES | MANAGER_ROLES,
    "schedule_range": ADMIN_ROLES | MANAGER_ROLES,
    "create_link": ADMIN_ROLES | MANAGER_ROLES,
    "status": ADMIN_ROLES | MANAGER_ROLES,
    "revoke": ADMIN_ROLES | MANAGER_ROLES,
    "rotate_key": ADMIN_ROLES | MANAGER_ROLES,
}

class ActionRolePermission(BasePermission):
    """Check that the user role is allowed for the action or model."""

    def has_permission(self, request, view):
        if request.user.is_superuser:
            return True
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
