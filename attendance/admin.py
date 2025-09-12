from datetime import timedelta

from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django import forms
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import path

from pagasys.admin import ScopedAdminMixin
from pagasys.models import Employee
from .models import AttDay, AttPair, AttAdjustment, LeaveRequest, LeaveDay
from .tasks import compute_employee_day_task, recompute_range_task


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
    list_filter = ("date", "status", "is_holiday", "is_rest_day", "locked")
    date_hierarchy = "date"
    search_fields = ("employee__first_name", "employee__last_name")
    readonly_fields = ("computed_at",)
    change_list_template = "admin/attendance/attday/change_list.html"
    actions = [
        "recompute_selected",
        "lock_selected",
        "unlock_selected",
        "manual_recompute",
    ]

    class ManualRecomputeForm(forms.Form):
        start = forms.DateField()
        end = forms.DateField()
        employee_ids = forms.CharField(
            required=False,
            help_text="Comma-separated employee IDs",
        )

        def clean_employee_ids(self):
            raw = self.cleaned_data.get("employee_ids", "")
            ids = []
            for part in raw.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    ids.append(int(part))
                except ValueError:
                    raise forms.ValidationError("Employee IDs must be integers")
            return ids

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "manual-recompute/",
                self.admin_site.admin_view(self.manual_recompute_view),
                name="attendance_attday_manual_recompute",
            )
        ]
        return custom + urls

    def manual_recompute_view(self, request):
        return self.manual_recompute(request, AttDay.objects.none())

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


    MAX_RANGE_DAYS = 31
    MAX_EMPLOYEES = 50

    def manual_recompute(self, request, queryset):  # pragma: no cover - admin view
        """Render a form to manually queue recomputation for a date span."""
        if request.POST.get('post'):
            form = self.ManualRecomputeForm(request.POST)
            if form.is_valid():
                start = form.cleaned_data['start']
                end = form.cleaned_data['end']
                if end < start or (end - start).days > self.MAX_RANGE_DAYS:
                    self.message_user(
                        request,
                        f"Range must be within {self.MAX_RANGE_DAYS} days",
                        level=messages.ERROR,
                    )
                    return redirect(request.get_full_path())
                ids = form.cleaned_data['employee_ids']
                qs = (
                    Employee.objects.filter(id__in=ids)
                    if ids
                    else Employee.objects.filter(is_active=True)
                )
                eids = list(qs.values_list('id', flat=True)[: self.MAX_EMPLOYEES])
                recompute_range_task.delay(
                    eids, start.isoformat(), end.isoformat()
                )
                self.message_user(
                    request,
                    f"Queued recompute for {len(eids)} employees",
                )
                return redirect(request.get_full_path())
        else:
            form = self.ManualRecomputeForm()
        context = {'form': form, 'title': 'Manual recompute'}
        return TemplateResponse(request, 'admin/manual_recompute.html', context)

    manual_recompute.short_description = "Manual recompute by date range"
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
