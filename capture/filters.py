import django_filters as df
from django.db.models import Q

from pagasys.filters import NumberInFilter

from .models import AttendanceDevice, PunchEvent


class AttendanceDeviceFilter(df.FilterSet):
    is_active = df.BooleanFilter()
    branch = df.NumberFilter(field_name="branch_id")
    department = df.NumberFilter(field_name="department_id")
    project = df.NumberFilter(field_name="project_id")

    class Meta:
        model = AttendanceDevice
        fields = ["is_active", "branch", "department", "project"]


class PunchEventFilter(df.FilterSet):
    employee = df.NumberFilter(field_name="employee_id")
    device = df.NumberFilter(field_name="device_id")
    branch = NumberInFilter(method="filter_branch")
    date_from = df.DateFilter(field_name="device_ts", lookup_expr="date__gte")
    date_to = df.DateFilter(field_name="device_ts", lookup_expr="date__lte")
    face_matched = df.BooleanFilter()
    out_of_scope = df.BooleanFilter()
    geofence_ok = df.BooleanFilter()
    geofence_rule_violation = df.BooleanFilter()
    roster_fallback = df.BooleanFilter()

    def filter_branch(self, qs, name, value):
        if not value:
            return qs
        branch_filter = Q(device__branch_id__in=value)
        branch_filter |= Q(employee__department__branch_id__in=value)
        branch_filter |= Q(employee__project__branch_id__in=value)
        branch_filter |= Q(matched_employee__department__branch_id__in=value)
        branch_filter |= Q(matched_employee__project__branch_id__in=value)
        return qs.filter(branch_filter).distinct()

    class Meta:
        model = PunchEvent
        fields = [
            "employee",
            "device",
            "branch",
            "face_matched",
            "out_of_scope",
            "geofence_ok",
            "geofence_rule_violation",
            "roster_fallback",
        ]
