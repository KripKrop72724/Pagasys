from django.db import models

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
)


ROLE_PRIORITY = [
    ("Company Admin", "company_admin"),
    ("Payroll Manager", "payroll_manager"),
    ("Branch Manager", "branch_manager"),
    ("Department Manager", "department_manager"),
    ("Project Manager", "project_manager"),
    ("Employee", "employee"),
]


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
        if role in ("company_admin", "payroll_manager"):
            return queryset.filter(trade_license__company=company)
        if role == "branch_manager" and branch:
            return queryset.filter(
                models.Q(department__branch=branch) | models.Q(project__branch=branch)
            )
        if role == "department_manager" and user.department:
            return queryset.filter(department=user.department)
        if role == "project_manager" and user.project:
            return queryset.filter(project=user.project)
        return queryset.filter(pk=user.pk)

    return queryset

