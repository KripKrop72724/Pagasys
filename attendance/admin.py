from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django import forms

from pagasys.admin import ScopedAdminMixin
from .models import AttDay, AttPair, AttAdjustment, LeaveRequest, LeaveDay
from .tasks import compute_employee_day_task


class AttAdjustmentForm(forms.ModelForm):
    class Meta:
        model = AttAdjustment
        fields = "__all__"
        help_texts = {
            "delta_work_min": "Additive minutes applied to work_min",
            "delta_unpaid_break_min": "Additive minutes applied to unpaid_break_min",
            "delta_paid_break_min": "Additive minutes applied to paid_break_min",
            "delta_ot_regular_min": "Additive minutes applied to ot_regular_min",
            "delta_ot_night_min": "Additive minutes applied to ot_night_min",
            "delta_ot_holiday_min": "Additive minutes applied to ot_holiday_min",
            "override_status": "Override final status (e.g. 'present')",
        }


@admin.register(AttDay)
class AttDayAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Admin interface for computed daily attendance results."""

    list_display = ("employee", "date", "status", "work_min", "locked")
    list_filter = ("status", "is_holiday", "is_rest_day", "locked")
    search_fields = ("employee__first_name", "employee__last_name")
    readonly_fields = ("computed_at",)
    actions = ["recompute_selected", "lock_selected", "unlock_selected"]

    def changelist_view(self, request, extra_context=None):
        self.message_user(
            request,
            mark_safe(
                'See <a href="https://github.com/your-org/your-repo/blob/main/README.md#attendance-computation-layer" target="_blank">README</a> and '
                '<a href="/api/schema/" target="_blank">API docs</a> for guidance.'
            ),
            level=messages.INFO,
        )
        return super().changelist_view(request, extra_context)

    def recompute_selected(self, request, queryset):
        for day in queryset:
            compute_employee_day_task.delay(day.employee_id, day.date.isoformat())
        self.message_user(request, f"Queued {queryset.count()} days for recompute")

    recompute_selected.short_description = (
        "Recompute selected days to refresh payroll totals"
    )

    def lock_selected(self, request, queryset):
        queryset.update(locked=True)

    lock_selected.short_description = (
        "Lock selected days to freeze numbers for payroll"
    )

    def unlock_selected(self, request, queryset):
        queryset.update(locked=False)

    unlock_selected.short_description = (
        "Unlock days so recomputation can adjust payroll"
    )


@admin.register(AttPair)
class AttPairAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Review paired IN/OUT punch sessions."""

    list_display = ("employee", "date", "in_ts", "out_ts", "duration_min")
    list_filter = ("source",)
    search_fields = ("employee__first_name", "employee__last_name")
    readonly_fields = ("created_at", "updated_at")

    def changelist_view(self, request, extra_context=None):
        self.message_user(
            request,
            mark_safe(
                'See <a href="https://github.com/your-org/your-repo/blob/main/README.md#attendance-computation-layer" target="_blank">README</a> and '
                '<a href="/api/schema/" target="_blank">API docs</a> for pairing details.'
            ),
            level=messages.INFO,
        )
        return super().changelist_view(request, extra_context)


@admin.register(LeaveRequest)
class LeaveRequestAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Manage employee leave requests."""

    list_display = ("employee", "leave_type", "date_from", "date_to", "status")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__first_name", "employee__last_name")

    def changelist_view(self, request, extra_context=None):
        self.message_user(
            request,
            mark_safe(
                'See <a href="https://github.com/your-org/your-repo/blob/main/README.md#attendance-computation-layer" '
                'target="_blank">README</a> and <a href="/api/schema/" target="_blank">API docs</a> for leave workflow details.'
            ),
            level=messages.INFO,
        )
        return super().changelist_view(request, extra_context)


@admin.register(LeaveDay)
class LeaveDayAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """View materialized leave per day."""

    list_display = ("employee", "date", "leave_type", "portion")
    list_filter = ("leave_type",)
    search_fields = ("employee__first_name", "employee__last_name")
    readonly_fields = ("created_at",)

    def changelist_view(self, request, extra_context=None):
        self.message_user(
            request,
            mark_safe(
                'See <a href="https://github.com/your-org/your-repo/blob/main/README.md#attendance-computation-layer" '
                'target="_blank">README</a> and <a href="/api/schema/" target="_blank">API docs</a> for leave day guidance.'
            ),
            level=messages.INFO,
        )
        return super().changelist_view(request, extra_context)


@admin.register(AttAdjustment)
class AttAdjustmentAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Review and edit manual attendance adjustments."""

    list_display = (
        "employee",
        "date",
        "delta_work_min",
        "delta_ot_regular_min",
        "override_status",
    )
    search_fields = ("employee__first_name", "employee__last_name")
    list_filter = ("override_status",)
    readonly_fields = ("created_at",)
    form = AttAdjustmentForm

    def changelist_view(self, request, extra_context=None):
        self.message_user(
            request,
            mark_safe(
                'See <a href="https://github.com/your-org/your-repo/blob/main/README.md#attendance-computation-layer" target="_blank">README</a> and '
                '<a href="/api/schema/" target="_blank">API docs</a> for adjustment guidance.'
            ),
            level=messages.INFO,
        )
        return super().changelist_view(request, extra_context)
