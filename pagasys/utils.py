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


def user_role(user):
    if user.is_superuser:
        return "superuser"
    groups = {g.name for g in user.groups.all()}
    if "Company Admin" in groups:
        return "company_admin"
    if "Payroll Manager" in groups:
        return "payroll_manager"
    if "Branch Manager" in groups:
        return "branch_manager"
    if "Department Manager" in groups:
        return "department_manager"
    if "Project Manager" in groups:
        return "project_manager"
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

