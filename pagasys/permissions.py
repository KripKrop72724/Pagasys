from rest_framework.permissions import BasePermission
from django.contrib.auth.models import Group


class IsInGroup(BasePermission):
    """Base class to check if user belongs to a specific group."""

    group_name: str = ""

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated and request.user.groups.filter(name=self.group_name).exists()

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


def make_group_permission(name: str):
    return type(name, (IsInGroup,), {"group_name": name})


IsBranchManager = make_group_permission("Branch Manager")
IsCompanyAdmin = make_group_permission("Company Admin")
IsPayrollManager = make_group_permission("Payroll Manager")
IsDepartmentManager = make_group_permission("Department Manager")
IsProjectManager = make_group_permission("Project Manager")
IsEmployee = make_group_permission("Employee")
