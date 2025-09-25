from datetime import date, timedelta
from urllib.parse import urlsplit
from types import SimpleNamespace

from django.contrib import admin, messages
from django.utils.safestring import mark_safe
from django import forms
from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.http import HttpResponse, QueryDict
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q

from rest_framework import serializers
from rest_framework.request import Request

from pagasys.admin import ScopedAdminMixin
from pagasys.models import Branch, Department, Employee, Project, ShiftTemplate
from pagasys.utils import scope_queryset
from capture.models import PunchEvent

from .models import AttDay, AttPair, AttAdjustment, LeaveRequest, LeaveDay
from .tasks import compute_employee_day_task, recompute_range_task
from .reports import (
    get_late_comers,
    group_late_comers,
    render_late_comers_pdf,
    render_monthly_attendance_pdf,
)
from .views import (
    AttendanceCalendarViewSet,
    CALENDAR_PAGE_SIZE,
    parse_bool,
    parse_month,
)
from .services import build_monthly_calendar
from .services_helpers import compute_full_attendance_delta, get_day_context
from .forms import MonthlyAttendanceReportForm


class AttAdjustmentForm(forms.ModelForm):
    mark_full_attendance = forms.BooleanField(
        required=False,
        label="Mark full attendance",
        help_text=(
            "When selected, delta_work_min is auto-filled with the minutes "
            "needed to reach the scheduled shift total."
        ),
    )
    class Meta:
        model = AttAdjustment
        exclude = ["created_by_id"]
        help_texts = {
            "delta_work_min": "Additive minutes applied to work_min",
            "delta_unpaid_break_min": "Additive minutes applied to unpaid_break_min",
            "delta_paid_break_min": "Additive minutes applied to paid_break_min",
            "delta_ot_regular_min": "Additive minutes applied to ot_regular_min",
            "delta_ot_night_min": "Additive minutes applied to ot_night_min",
            "delta_ot_holiday_min": "Additive minutes applied to ot_holiday_min",
            "override_status": "Override final status (e.g. 'present')",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        optional_fields = [
            "delta_work_min",
            "delta_unpaid_break_min",
            "delta_paid_break_min",
            "delta_ot_regular_min",
            "delta_ot_night_min",
            "delta_ot_holiday_min",
        ]
        for name in optional_fields:
            if name in self.fields:
                self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("mark_full_attendance"):
            employee = cleaned.get("employee") or getattr(
                self.instance, "employee", None
            )
            date_value = cleaned.get("date") or getattr(
                self.instance, "date", None
            )
            if not employee or not date_value:
                raise forms.ValidationError(
                    {
                        "mark_full_attendance": (
                            "Employee and date are required to mark full attendance."
                        )
                    }
                )
            try:
                delta = compute_full_attendance_delta(employee.id, date_value)
            except ValueError as exc:
                raise forms.ValidationError(
                    {"mark_full_attendance": str(exc)}
                ) from exc
            cleaned["delta_work_min"] = delta
            self.cleaned_data["delta_work_min"] = delta
            self.instance.delta_work_min = delta
        return cleaned


class QuickAttAdjustmentForm(AttAdjustmentForm):
    class Meta(AttAdjustmentForm.Meta):
        exclude = [*AttAdjustmentForm.Meta.exclude, "employee", "date"]


class EmployeeBranchListFilter(admin.SimpleListFilter):
    title = "branch"
    parameter_name = "branch"

    def lookups(self, request, model_admin):
        qs = scope_queryset(Branch.objects.all(), request.user)
        return [(branch.pk, branch.name) for branch in qs.order_by("name")]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        try:
            branch_id = int(value)
        except (TypeError, ValueError):
            return queryset
        branch_filter = Q(employee__department__branch_id=branch_id) | Q(
            employee__project__branch_id=branch_id
        )
        return queryset.filter(branch_filter)


@admin.register(AttDay)
class AttDayAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Admin interface for computed daily attendance results."""

    list_display = ("employee", "date", "status", "work_min", "locked")
    list_filter = (
        "date",
        "status",
        "is_holiday",
        "is_rest_day",
        "locked",
        EmployeeBranchListFilter,
    )
    date_hierarchy = "date"
    search_fields = ("employee__first_name", "employee__last_name")
    autocomplete_fields = ["employee", "roster"]
    readonly_fields = ("computed_at",)
    change_list_template = "admin/attendance/attday/change_list.html"
    change_form_template = "admin/attendance/attday/change_form.html"
    actions = [
        "recompute_selected",
        "lock_selected",
        "unlock_selected",
        "manual_recompute",
    ]

    @staticmethod
    def _format_validation_error(exc):
        detail = getattr(exc, "detail", exc)
        if isinstance(detail, dict):
            parts = []
            for key, value in detail.items():
                if isinstance(value, (list, tuple)):
                    message = ", ".join(str(item) for item in value)
                else:
                    message = str(value)
                if key:
                    parts.append(f"{key}: {message}")
                else:
                    parts.append(message)
            return "; ".join(parts)
        if isinstance(detail, (list, tuple)):
            return "; ".join(str(item) for item in detail)
        return str(detail)

    @staticmethod
    def _relative_link(link):
        if not link:
            return None
        parts = urlsplit(link)
        path = parts.path
        if parts.query:
            path = f"{path}?{parts.query}"
        return path

    def _parse_bool_param(self, request, name, *, default=False):
        value = request.GET.get(name)
        if value is None:
            return default
        try:
            return parse_bool(value, default=default)
        except serializers.ValidationError:
            self.message_user(
                request,
                f"Invalid value for '{name}'. Using default.",
                level=messages.WARNING,
            )
            return default

    def calendar_view(self, request):
        query = request.GET.copy()
        default_month = timezone.localdate().strftime("%Y-%m")

        def redirect_with_params(params):
            encoded = params.urlencode()
            if encoded:
                return redirect(f"{request.path}?{encoded}")
            return redirect(request.path)

        if not query.get("month"):
            query["month"] = default_month
            if "cursor" in query:
                del query["cursor"]
            return redirect_with_params(query)

        month_value = query.get("month")
        try:
            start, end = parse_month(month_value)
        except serializers.ValidationError as exc:
            self.message_user(
                request,
                self._format_validation_error(exc),
                level=messages.ERROR,
            )
            query["month"] = default_month
            if "cursor" in query:
                del query["cursor"]
            return redirect_with_params(query)

        include_pairs = self._parse_bool_param(
            request, "include_pairs", default=False
        )
        include_adjustments = self._parse_bool_param(
            request, "include_adjustments", default=False
        )
        include_anomalies = self._parse_bool_param(
            request, "include_anomalies", default=True
        )

        stats_only = False
        if request.GET.get("stats_only") is not None:
            try:
                requested_stats = parse_bool(request.GET.get("stats_only"))
            except serializers.ValidationError:
                self.message_user(
                    request,
                    "Invalid value for 'stats_only'. Showing full calendar instead.",
                    level=messages.WARNING,
                )
            else:
                if requested_stats:
                    self.message_user(
                        request,
                        "Stats-only mode is not available in the admin calendar view. Displaying the full grid.",
                        level=messages.INFO,
                    )

        status_param = request.GET.get("status")
        status_filters = (
            [value.strip() for value in status_param.split(",") if value.strip()]
            if status_param
            else []
        )

        locked_filter = None
        if "locked" in request.GET:
            try:
                locked_filter = parse_bool(request.GET.get("locked"))
            except serializers.ValidationError:
                self.message_user(
                    request,
                    "Invalid value for 'locked'. Showing all days.",
                    level=messages.WARNING,
                )
                locked_filter = None

        viewset = AttendanceCalendarViewSet()
        drf_request = Request(request)
        drf_request.user = request.user
        viewset.request = drf_request
        viewset.args = []
        viewset.kwargs = {}
        viewset.action = "list"
        viewset.format_kwarg = None

        queryset = viewset._filter_employees(viewset.get_queryset(), drf_request, None)
        queryset = viewset._apply_sorting(queryset, drf_request)

        page = viewset.paginate_queryset(queryset)
        paginator = getattr(viewset, "paginator", None)
        all_requested = bool(getattr(paginator, "all_requested", False)) if paginator else False

        employees = []
        using_pagination = False
        if page is not None:
            employees = list(page)
            using_pagination = True
            if not employees and queryset.exists():
                employees = list(queryset[:CALENDAR_PAGE_SIZE])
                using_pagination = False
        elif all_requested:
            employees = list(queryset)
        else:
            employees = list(queryset[:CALENDAR_PAGE_SIZE])

        if not using_pagination and not all_requested and len(employees) > CALENDAR_PAGE_SIZE:
            employees = employees[:CALENDAR_PAGE_SIZE]

        calendar_result = build_monthly_calendar(
            employees,
            (start, end),
            user=request.user,
            include_pairs=include_pairs,
            include_adjustments=include_adjustments,
            include_anomalies=include_anomalies,
            stats_only=stats_only,
            status_filters=status_filters,
            locked_filter=locked_filter,
            serializer_context=viewset.get_serializer_context(),
        )
        payload = calendar_result["payload"]

        paginator = getattr(viewset, "paginator", None)
        next_link = previous_link = None
        if paginator and using_pagination:
            next_link = self._relative_link(paginator.get_next_link())
            previous_link = self._relative_link(paginator.get_previous_link())

        days_context = []
        for iso_day in payload.get("days", []):
            current = date.fromisoformat(iso_day)
            days_context.append(
                {
                    "iso": iso_day,
                    "date": current,
                    "weekday": current.strftime("%a"),
                    "is_weekend": current.weekday() >= 5,
                }
            )

        employees_context = []
        for item in payload.get("employees", []):
            metadata = item.get("metadata") or {}
            summary = item.get("summary") or {}
            rows = []
            for row in item.get("rows", []):
                metrics = row.get("metrics", {})
                total_ot = (
                    metrics.get("ot_regular_min", 0)
                    + metrics.get("ot_night_min", 0)
                    + metrics.get("ot_holiday_min", 0)
                )
                status_value = row.get("status")
                status_class = (status_value or "empty").replace("_", "-")
                status_display = (
                    status_value.replace("_", " ").title() if status_value else "—"
                )
                rows.append(
                    {
                        **row,
                        "total_ot": total_ot,
                        "metrics": metrics,
                        "anomalies": row.get("anomalies", {}),
                        "pairs": row.get("pairs", []),
                        "adjustments": row.get("adjustments", []),
                        "status_class": status_class,
                        "status_display": status_display,
                    }
                )

            metadata_tags = []
            if metadata.get("department"):
                metadata_tags.append({"label": metadata["department"], "name": "Department"})
            if metadata.get("project"):
                metadata_tags.append({"label": metadata["project"], "name": "Project"})
            if metadata.get("branch"):
                metadata_tags.append({"label": metadata["branch"], "name": "Branch"})

            summary_definitions = [
                ("present", "Present", "present"),
                ("absent", "Absent", "absent"),
                ("leave", "Leave", "leave"),
                ("holiday", "Holiday", "holiday"),
                ("rest", "Rest day", "rest"),
                ("partial", "Partial", "partial"),
            ]
            summary_items = []
            for key, label, css in summary_definitions:
                value = summary.get(key, 0)
                summary_items.append(
                    {
                        "key": key,
                        "label": label,
                        "value": value,
                        "css": css,
                        "is_zero": value == 0,
                    }
                )
            summary_items.append(
                {
                    "key": "locked_days",
                    "label": "Locked",
                    "value": summary.get("locked_days", 0),
                    "css": "locked",
                    "is_zero": summary.get("locked_days", 0) == 0,
                }
            )
            summary_items.append(
                {
                    "key": "total_ot_min",
                    "label": "OT min",
                    "value": summary.get("total_ot_min", 0),
                    "css": "ot",
                    "is_zero": summary.get("total_ot_min", 0) == 0,
                }
            )

            employees_context.append(
                {
                    "id": item.get("id"),
                    "display": item.get("display"),
                    "metadata": metadata,
                    "metadata_tags": metadata_tags,
                    "code": metadata.get("code"),
                    "rows": rows,
                    "summary": summary,
                    "summary_items": summary_items,
                }
            )

        hidden_params = []
        excluded = {
            "month",
            "search",
            "include_pairs",
            "include_adjustments",
            "include_anomalies",
            "cursor",
            "stats_only",
        }
        for key, values in request.GET.lists():
            if key in excluded:
                continue
            for value in values:
                hidden_params.append((key, value))

        context = {
            "title": "Attendance calendar",
            "month_value": start.strftime("%Y-%m"),
            "month_display": start.strftime("%B %Y"),
            "days": days_context,
            "employees": employees_context,
            "employee_count": len(employees_context),
            "include_pairs": include_pairs,
            "include_adjustments": include_adjustments,
            "include_anomalies": include_anomalies,
            "search_value": request.GET.get("search", ""),
            "hidden_params": hidden_params,
            "next_link": next_link,
            "previous_link": previous_link,
            "page_size": CALENDAR_PAGE_SIZE,
        }

        return TemplateResponse(
            request, "admin/attendance/attday/calendar.html", context
        )

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

    def _message_form_errors(self, request, form):
        for field, errors in form.errors.items():
            label = field
            if field in form.fields:
                label = form.fields[field].label or field
            for error in errors:
                if field == "__all__":
                    self.message_user(request, error, level=messages.ERROR)
                else:
                    self.message_user(
                        request, f"{label}: {error}", level=messages.ERROR
                    )

    def _report_validation_errors(self, request, exc):
        handled = False
        if hasattr(exc, "message_dict"):
            for field, messages_list in exc.message_dict.items():
                for message in messages_list:
                    handled = True
                    if field and field != "__all__":
                        self.message_user(
                            request,
                            f"{field.replace('_', ' ').title()}: {message}",
                            level=messages.ERROR,
                        )
                    else:
                        self.message_user(request, message, level=messages.ERROR)
        if not handled:
            for message in getattr(exc, "messages", [str(exc)]):
                self.message_user(request, message, level=messages.ERROR)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related(
            "shift",
            "roster",
            "roster__shift",
            "employee",
            "employee__department__branch__company",
            "employee__project__branch__company",
        )

    def _build_day_related_context(self, day):
        pair_queryset = (
            AttPair.objects.filter(employee=day.employee, date=day.date)
            .order_by("in_ts")
            .only(
                "id",
                "in_ts",
                "out_ts",
                "duration_min",
                "cross_midnight",
                "source",
                "anomaly",
                "in_event_id",
                "out_event_id",
            )
        )
        punch_queryset = (
            PunchEvent.objects.filter(
                Q(employee_id=day.employee_id)
                | Q(matched_employee_id=day.employee_id)
            )
            .filter(Q(roster_date=day.date) | Q(device_ts__date=day.date))
            .select_related(
                "device",
                "device__company",
                "device__branch",
                "device__department",
                "device__project",
                "exception",
            )
            .order_by("device_ts")
        )
        context = get_day_context(
            day,
            include_pairs=True,
            include_punches=True,
            include_adjustments=False,
            include_admin_urls=True,
            pair_queryset=pair_queryset,
            punch_queryset=punch_queryset,
        )
        return {
            "roster_overview": context.get("roster_overview"),
            "pair_sessions": context.get("pair_sessions", []),
            "punch_events": context.get("punch_events", []),
        }

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        day = None
        if object_id is not None:
            day = self.get_object(request, object_id)
        if day is not None:
            extra_context.setdefault("quick_adjustment_form", QuickAttAdjustmentForm())
            extra_context["quick_adjustment_target"] = day
            extra_context["quick_adjustment_url"] = reverse(
                "admin:attendance_attday_add_adjustment", args=[day.pk]
            )
            extra_context.update(self._build_day_related_context(day))
        else:
            extra_context.setdefault("quick_adjustment_form", None)
            extra_context["quick_adjustment_target"] = None
            extra_context["quick_adjustment_url"] = None
            extra_context.setdefault("roster_overview", None)
            extra_context.setdefault("pair_sessions", [])
            extra_context.setdefault("punch_events", [])
        return super().changeform_view(request, object_id, form_url, extra_context)

    def add_adjustment_view(self, request, object_id):
        day = self.get_object(request, object_id)
        if day is None:
            return self._get_obj_does_not_exist_redirect(
                request, request.path, object_id
            )
        if not self.has_change_permission(request, day):
            raise PermissionDenied
        if request.method != "POST":
            return redirect(reverse("admin:attendance_attday_change", args=[object_id]))

        form = QuickAttAdjustmentForm(request.POST)
        # Ensure model-level validation sees the scoped employee/date before
        # ``is_valid`` triggers ``AttAdjustment.clean`` checks.
        form.instance.employee = day.employee
        form.instance.date = day.date
        form.instance.created_by_id = request.user.id
        if form.is_valid():
            adjustment = form.save(commit=False)
            adjustment.employee = day.employee
            adjustment.date = day.date
            adjustment.created_by_id = request.user.id
            try:
                adjustment.save()
            except ValidationError as exc:
                self._report_validation_errors(request, exc)
            else:
                self.message_user(
                    request,
                    "Attendance adjustment added successfully.",
                    level=messages.SUCCESS,
                )
                return redirect(
                    reverse("admin:attendance_attday_change", args=[object_id])
                )
        else:
            self._message_form_errors(request, form)

        return redirect(reverse("admin:attendance_attday_change", args=[object_id]))

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

    class LateComersReportForm(forms.Form):
        start = forms.DateField(
            widget=forms.DateInput(attrs={"type": "date"})
        )
        end = forms.DateField(
            widget=forms.DateInput(attrs={"type": "date"})
        )
        branch = forms.ModelChoiceField(
            queryset=Branch.objects.none(),
            required=False,
            empty_label="All branches",
        )
        department = forms.ModelChoiceField(
            queryset=Department.objects.none(),
            required=False,
            empty_label="All departments",
        )
        project = forms.ModelChoiceField(
            queryset=Project.objects.none(),
            required=False,
            empty_label="All projects",
        )
        shift = forms.ModelChoiceField(
            queryset=ShiftTemplate.objects.none(),
            required=False,
            empty_label="All shifts",
        )

        def __init__(self, *args, **kwargs):
            request = kwargs.pop("request", None)
            super().__init__(*args, **kwargs)
            queryset_map = {
                "branch": Branch,
                "department": Department,
                "project": Project,
                "shift": ShiftTemplate,
            }
            for field_name, model in queryset_map.items():
                qs = model.objects.all()
                if request is not None:
                    qs = scope_queryset(qs, request.user)
                self.fields[field_name].queryset = qs

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<path:object_id>/add-adjustment/",
                self.admin_site.admin_view(self.add_adjustment_view),
                name="attendance_attday_add_adjustment",
            ),
            path(
                "calendar/",
                self.admin_site.admin_view(self.calendar_view),
                name="attendance_attday_calendar",
            ),
            path(
                "manual-recompute/",
                self.admin_site.admin_view(self.manual_recompute_view),
                name="attendance_attday_manual_recompute",
            ),
            path(
                "late-comers-report/",
                self.admin_site.admin_view(self.late_comers_report_view),
                name="attendance_attday_late_comers_report",
            ),
            path(
                "monthly-attendance-report/",
                self.admin_site.admin_view(self.monthly_attendance_report_view),
                name="attendance_attday_monthly_report",
            ),
        ]
        return custom + urls

    def late_comers_report_view(self, request):  # pragma: no cover - admin view
        return self.late_comers_report(request)

    def monthly_attendance_report_view(self, request):  # pragma: no cover - admin view
        return self.monthly_attendance_report(request)

    def late_comers_report(self, request):  # pragma: no cover - admin view
        if request.method == "POST":
            form = self.LateComersReportForm(request.POST, request=request)
            if form.is_valid():
                start = form.cleaned_data["start"]
                end = form.cleaned_data["end"]
                filters = {}
                for key in ["branch", "department", "project", "shift"]:
                    obj = form.cleaned_data.get(key)
                    if obj is not None:
                        filters[f"{key}_id"] = obj.pk
                records = get_late_comers(start, end, filters)
                branches, stats = group_late_comers(records)
                pdf = render_late_comers_pdf(branches, stats, start, end, request)
                response = HttpResponse(pdf, content_type="application/pdf")
                response["Content-Disposition"] = (
                    f"attachment; filename=late_comers_{start}_{end}.pdf"
                )
                return response
        else:
            form = self.LateComersReportForm(request=request)
        context = {"form": form, "title": "Late comers report"}
        return TemplateResponse(request, "admin/late_comers_report.html", context)

    def monthly_attendance_report(self, request):  # pragma: no cover - admin view
        form_kwargs = {"request": request}
        status_choices = dict(AttDay._meta.get_field("status").choices)
        if request.method == "POST":
            form = MonthlyAttendanceReportForm(request.POST, **form_kwargs)
            if form.is_valid():
                month_value = form.cleaned_data["month"]
                start, end = parse_month(month_value)

                viewset = AttendanceCalendarViewSet()
                drf_request = Request(request)
                drf_request.user = request.user
                viewset.request = drf_request
                viewset.args = []
                viewset.kwargs = {}
                viewset.action = "monthly_report"
                viewset.format_kwarg = None

                params = QueryDict(mutable=True)
                branch = form.cleaned_data.get("branch")
                department = form.cleaned_data.get("department")
                project = form.cleaned_data.get("project")
                statuses = form.cleaned_statuses()
                locked_value = form.cleaned_locked_value()

                if branch:
                    params.setlist("branch", [str(branch.pk)])
                if department:
                    params.setlist("department", [str(department.pk)])
                if project:
                    params.setlist("project", [str(project.pk)])
                if statuses:
                    params["status"] = ",".join(statuses)
                if locked_value is not None:
                    params["locked"] = "true" if locked_value else "false"

                filter_request = SimpleNamespace(query_params=params)
                queryset = viewset._filter_employees(viewset.get_queryset(), filter_request, None)
                queryset = viewset._apply_sorting(queryset, filter_request)
                employees = list(queryset)

                calendar_result = build_monthly_calendar(
                    employees,
                    (start, end),
                    user=request.user,
                    include_pairs=False,
                    include_adjustments=False,
                    include_anomalies=False,
                    stats_only=False,
                    status_filters=statuses,
                    locked_filter=locked_value,
                    serializer_context=viewset.get_serializer_context(),
                )

                filters_summary = {
                    "branch": [branch.name] if branch else [],
                    "department": [department.name] if department else [],
                    "project": [project.name] if project else [],
                    "status": [status_choices.get(code, code) for code in statuses],
                    "locked": (
                        "Locked only" if locked_value is True else "Unlocked only" if locked_value is False else ""
                    ),
                }

                pdf_context = {
                    "request": request,
                    "filters": filters_summary,
                    "title": "Monthly attendance report",
                }
                pdf = render_monthly_attendance_pdf(calendar_result["report"], pdf_context)
                filename = f"monthly_attendance_{month_value}.pdf"
                response = HttpResponse(pdf, content_type="application/pdf")
                response["Content-Disposition"] = f"attachment; filename={filename}"
                return response
        else:
            form = MonthlyAttendanceReportForm(**form_kwargs)

        context = {"form": form, "title": "Monthly attendance report"}
        return TemplateResponse(request, "admin/monthly_attendance_report.html", context)
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

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by_id = request.user.id
        super().save_model(request, obj, form, change)
