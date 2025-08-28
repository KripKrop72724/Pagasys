from django.contrib import admin
from pagasys.utils import scope_queryset
from .models import AttendanceDevice, FaceEnrollment, EnrollmentLink, PunchEvent, PunchException


class ScopedAdminMixin:
    def get_queryset(self, request):
        return scope_queryset(super().get_queryset(request), request.user)


@admin.register(AttendanceDevice)
class AttendanceDeviceAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "name",
        "company",
        "branch",
        "department",
        "project",
        "is_active",
        "last_seen",
        "latitude",
        "longitude",
        "radius_m",
        "note",
    ]
    list_filter = ["company", "branch", "department", "project", "is_active"]
    search_fields = ["name", "api_key"]


@admin.register(FaceEnrollment)
class FaceEnrollmentAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ["employee", "status", "created_at", "updated_at"]


@admin.register(EnrollmentLink)
class EnrollmentLinkAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ["employee", "token", "expires_at", "used_at", "uses", "max_uses"]
    readonly_fields = ["uses", "used_at"]


@admin.register(PunchEvent)
class PunchEventAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = [
        "company",
        "device",
        "employee",
        "action",
        "device_ts",
        "face_matched",
        "face_confidence",
        "requires_face",
        "out_of_scope",
        "geofence_ok",
        "geofence_rule_violation",
        "roster_fallback",
        "roster_date",
        "external_id",
    ]
    list_filter = [
        "company",
        "device",
        "face_matched",
        "requires_face",
        "out_of_scope",
        "geofence_ok",
        "geofence_rule_violation",
        "roster_fallback",
        "roster_date",
    ]
    search_fields = ["employee__username", "device__name", "external_id"]


@admin.register(PunchException)
class PunchExceptionAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ["event", "kind", "details"]
    list_filter = ["kind"]
