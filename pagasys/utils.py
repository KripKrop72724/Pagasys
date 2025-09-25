from django.db import models
from rest_framework.exceptions import PermissionDenied

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
)
from capture.models import AttendanceDevice

SCOPED_MODELS = {
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
    AttendanceDevice,
}


ROLE_PRIORITY = [
    ("Company Admin", "company_admin"),
    ("Payroll Manager", "payroll_manager"),
    ("Branch Manager", "branch_manager"),
    ("Department Manager", "department_manager"),
    ("Project Manager", "project_manager"),
    ("Employee", "employee"),
]


def _company_id_value(company_or_id):
    """Normalize a company object or PK to a primary key value."""
    if company_or_id is None:
        return None
    return getattr(company_or_id, "pk", company_or_id)


def employee_company_q(company_or_id, *, field_prefix=""):
    """Return a Q filtering employees linked to the given company."""
    company_id = _company_id_value(company_or_id)
    if company_id is None:
        return models.Q(pk__in=[])
    prefix = f"{field_prefix}__" if field_prefix else ""
    return models.Q(**{f"{prefix}department__branch__company_id": company_id}) | models.Q(
        **{f"{prefix}project__branch__company_id": company_id}
    )


def user_role(user):
    """Determine the highest priority role for a user."""
    if user.is_superuser:
        return "superuser"
    user_groups = set(user.groups.values_list("name", flat=True))
    for group_name, role in ROLE_PRIORITY:
        if group_name in user_groups:
            return role
    return "employee"


def scope_queryset(queryset, user):
    role = user_role(user)
    if role == "superuser":
        return queryset

    model = queryset.model
    company = getattr(user, "company", None)
    branch = getattr(user, "branch", None)

    if model is Company:
        if company:
            return queryset.filter(pk=company.pk)
        return queryset.none()

    if model is Branch:
        if role == "company_admin" or role == "payroll_manager":
            return queryset.filter(company=company)
        if branch:
            return queryset.filter(pk=branch.pk)
        return queryset.none()

    if model is Designation:
        if company:
            return queryset.filter(company=company)
        return queryset.none()

    if model is TradeLicense:
        if company:
            return queryset.filter(company=company)
        return queryset.none()

    if model is Department:
        if role == "company_admin" or role == "payroll_manager":
            return queryset.filter(branch__company=company)
        if role == "branch_manager" and branch:
            return queryset.filter(branch=branch)
        if role == "department_manager" and user.department:
            return queryset.filter(pk=user.department.pk)
        if branch:
            return queryset.filter(branch=branch)
        return queryset.none()

    if model is Project:
        if role == "company_admin" or role == "payroll_manager":
            return queryset.filter(branch__company=company)
        if role == "branch_manager" and branch:
            return queryset.filter(branch=branch)
        if role == "project_manager" and user.project:
            return queryset.filter(pk=user.project.pk)
        if branch:
            return queryset.filter(branch=branch)
        return queryset.none()

    if model is Employee:
        if not user.is_superuser:
            queryset = queryset.filter(is_superuser=False)
        if role in ("company_admin", "payroll_manager"):
            if company:
                return queryset.filter(employee_company_q(company))
            return queryset.none()
        if role == "branch_manager" and branch:
            return queryset.filter(
                models.Q(department__branch=branch) | models.Q(project__branch=branch)
            )
        if role == "department_manager" and user.department:
            return queryset.filter(department=user.department)
        if role == "project_manager" and user.project:
            return queryset.filter(project=user.project)
        return queryset.filter(pk=user.pk)

    if model is WorkCalendar:
        if company:
            return queryset.filter(company=company)
        return queryset.none()

    if model is Holiday:
        if company:
            return queryset.filter(calendar__company=company)
        return queryset.none()

    if model is ShiftTemplate:
        if company:
            return queryset.filter(company=company)
        return queryset.none()

    if model is ShiftRule:
        if company:
            return queryset.filter(shift__company=company)
        return queryset.none()

    if model is RosterEntry:
        if role in ("company_admin", "payroll_manager") and company:
            return queryset.filter(employee_company_q(company, field_prefix="employee"))
        if role == "branch_manager" and branch:
            return queryset.filter(
                models.Q(employee__department__branch=branch)
                | models.Q(employee__project__branch=branch)
            )
        if role == "department_manager" and user.department:
            return queryset.filter(employee__department=user.department)
        if role == "project_manager" and user.project:
            return queryset.filter(employee__project=user.project)
        return queryset.filter(employee=user)

    if model is AttendanceDevice:
        if role in ("company_admin", "payroll_manager") and company:
            return queryset.filter(company=company)
        if role == "branch_manager" and branch:
            return queryset.filter(
                models.Q(branch=branch)
                | models.Q(department__branch=branch)
                | models.Q(project__branch=branch)
                | (
                    models.Q(branch__isnull=True)
                    & models.Q(department__isnull=True)
                    & models.Q(project__isnull=True)
                )
            )
        if role == "department_manager" and user.department:
            return queryset.filter(department=user.department)
        if role == "project_manager" and user.project:
            return queryset.filter(project=user.project)
        return queryset.none()

    if model is LeaveType:
        if company:
            return queryset.filter(company=company)
        return queryset.none()

    return queryset


def ensure_in_scope(obj, user, field_name=""):
    """Raise PermissionDenied if object is outside the user's scope."""
    if obj.__class__ not in SCOPED_MODELS:
        return
    qs = scope_queryset(obj.__class__.objects.filter(pk=obj.pk), user)
    if not qs.exists():
        prefix = f"{field_name}: " if field_name else ""
        raise PermissionDenied(f"{prefix}object not in allowed scope")
