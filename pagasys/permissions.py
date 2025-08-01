from rest_framework.permissions import BasePermission
from django.contrib.auth.models import Group


class CustomObjectPermission(BasePermission):
    """Restrict object-level access based on scoped queryset."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        qs = view.get_queryset()
        return qs.filter(pk=getattr(obj, 'pk')).exists()


class IsInGroup(BasePermission):
    """Base class to check if user belongs to a specific group."""

    group_name: str = ""

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.groups.filter(name=self.group_name).exists()
        )

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


class GroupRequiredPermission(BasePermission):
    """Require user to belong to at least one allowed group."""

    groups: list[str] = []

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        allowed = getattr(view, "required_groups", self.groups)
        if not allowed:
            return True
        return request.user.groups.filter(name__in=allowed).exists()

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
