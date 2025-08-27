import django_filters as df
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
    date_from = df.DateFilter(field_name="device_ts", lookup_expr="date__gte")
    date_to = df.DateFilter(field_name="device_ts", lookup_expr="date__lte")
    face_matched = df.BooleanFilter()
    out_of_scope = df.BooleanFilter()
    geofence_ok = df.BooleanFilter()

    class Meta:
        model = PunchEvent
        fields = ["employee", "device", "face_matched", "out_of_scope", "geofence_ok"]
