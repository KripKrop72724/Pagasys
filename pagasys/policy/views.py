from django.db import transaction
from django.utils.dateparse import parse_date
from django.db.models import Q, Count
from datetime import timedelta
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import (
    extend_schema,
    OpenApiExample,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes

from pagasys.models import (
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
    Employee,
    holiday_flags,
)
from .serializers import (
    WorkCalendarSerializer,
    HolidaySerializer,
    ShiftTemplateSerializer,
    ShiftRuleSerializer,
    ShiftRuleValidateResponseSerializer,
    RosterEntrySerializer,
    LeaveTypeSerializer,
    RosterRangeSerializer,
    HolidayImportRequest,
    HolidayImportResponseSerializer,
    ShiftTemplatePreviewSerializer,
    RosterBulkUpsertRequestSerializer,
    RosterBulkUpsertResponseSerializer,
    RosterSummarySerializer,
)
from .filters import (
    WorkCalendarFilter,
    HolidayFilter,
    ShiftTemplateFilter,
    ShiftRuleFilter,
    RosterFilter,
    LeaveTypeFilter,
)
from .permissions import IsCompanyMember, CompanyScopedQuerysetMixin, ActionRolePermission
from pagasys.openapi_utils import document_filters, _generate_parameters
from pagasys.utils import scope_queryset
from pagasys.tasks import schedule_range_bulk

ASYNC_BULK_THRESHOLD = 50

import django_filters.rest_framework as drf_filters
from rest_framework import filters as rest_filters
from .backends import ScopeFilterBackend

class BasePolicyViewSet(CompanyScopedQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsCompanyMember, ActionRolePermission]
    filter_backends = [
        ScopeFilterBackend,
        drf_filters.DjangoFilterBackend,
        rest_filters.OrderingFilter,
        rest_filters.SearchFilter,
    ]
    ordering_fields = "__all__"
    search_fields = []

    def perform_create(self, serializer):
        model = serializer.Meta.model
        company = self.get_company()
        if hasattr(model, "company_id"):
            serializer.save(company=company)
        else:
            serializer.save()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["company"] = self.get_company()
        return ctx

class WorkCalendarViewSet(BasePolicyViewSet):
    queryset = WorkCalendar.objects.all()
    serializer_class = WorkCalendarSerializer
    filterset_class = WorkCalendarFilter
    ordering = ["id"]
    search_fields = ["name"]

    @extend_schema(
        responses=HolidaySerializer(many=True),
        parameters=_generate_parameters(type('HolidayViewSet', (), {"filterset_class": HolidayFilter})),
    )
    @action(detail=True, methods=["get"])
    def holidays(self, request, company_id=None, pk=None):
        cal = self.get_object()
        qs = cal.holidays.all()
        f = HolidayFilter(request.GET, queryset=qs)
        page = self.paginate_queryset(f.qs)
        ser = HolidaySerializer(page or f.qs, many=True)
        return self.get_paginated_response(ser.data) if page else Response(ser.data)

    @extend_schema(
        description=(
            "Bulk import holidays. Each item accepts a 'date', 'name' and "
            "optional 'is_public' boolean flag."
        ),
        examples=[
            OpenApiExample(
                "Import example",
                value=[{"date": "2024-01-01", "name": "New Year", "is_public": True}],
            )
        ],
        request=HolidayImportRequest(many=True),
        responses=HolidayImportResponseSerializer,
    )
    @action(detail=True, methods=["post"], url_path="holidays/import")
    def import_holidays(self, request, company_id=None, pk=None):
        cal = self.get_object()
        items = request.data if isinstance(request.data, list) else []
        if not items:
            return Response({"detail": "Provide a list of holidays"}, status=400)
        to_create = []
        for it in items:
            d = parse_date(it.get("date"))
            if not d or not it.get("name"):
                return Response({"detail": f"Invalid item: {it}"}, status=400)
            to_create.append(
                Holiday(calendar=cal, date=d, name=it["name"], is_public=bool(it.get("is_public", False)))
            )
        with transaction.atomic():
            Holiday.objects.bulk_create(
                to_create,
                update_conflicts=True,
                update_fields=["name", "is_public"],
                unique_fields=["calendar", "date"],
            )
        payload = {"count": len(to_create)}
        return Response(HolidayImportResponseSerializer(payload).data, status=200)

class HolidayViewSet(BasePolicyViewSet):
    """Policy layer holiday operations.

    Updates or deletions enqueue recalculation of roster entries tied to the
    holiday's calendar so existing schedules stay in sync with calendar
    changes.
    """

    queryset = Holiday.objects.select_related("calendar", "calendar__company")
    serializer_class = HolidaySerializer
    filterset_class = HolidayFilter
    ordering = ["date"]
    search_fields = ["name"]

class ShiftTemplateViewSet(BasePolicyViewSet):
    queryset = ShiftTemplate.objects.all()
    serializer_class = ShiftTemplateSerializer
    filterset_class = ShiftTemplateFilter
    ordering = ["id"]
    search_fields = ["name"]

    @extend_schema(
        responses=ShiftRuleSerializer(many=True),
        parameters=_generate_parameters(type('ShiftRuleViewSet', (), {"filterset_class": ShiftRuleFilter})),
    )
    @action(detail=True, methods=["get"])
    def rules(self, request, company_id=None, pk=None):
        tpl = self.get_object()
        qs = tpl.rules.all()
        f = ShiftRuleFilter(request.GET, queryset=qs)
        page = self.paginate_queryset(f.qs)
        ser = ShiftRuleSerializer(page or f.qs, many=True)
        return self.get_paginated_response(ser.data) if page else Response(ser.data)

    @extend_schema(responses=ShiftTemplatePreviewSerializer)
    @action(detail=True, methods=["get"])
    def preview(self, request, company_id=None, pk=None):
        from pagasys.models import _minutes_between
        tpl = self.get_object()
        minutes = _minutes_between(tpl.start_time, tpl.end_time, tpl.cross_midnight)
        payload = {
            "id": tpl.id,
            "name": tpl.name,
            "duration_min": minutes,
            "unpaid_break_min": tpl.break_minutes,
            "rounded_increment_min": tpl.rounding_min,
            "cross_midnight": tpl.cross_midnight,
        }
        return Response(payload)

class ShiftRuleViewSet(BasePolicyViewSet):
    queryset = ShiftRule.objects.select_related("shift", "shift__company")
    serializer_class = ShiftRuleSerializer
    filterset_class = ShiftRuleFilter
    ordering = ["id"]

    @extend_schema(
        description="Dry-run a shift rule without saving. Demonstrates boolean flags in params.",
        examples=[
            OpenApiExample(
                "Paid break window",
                value={
                    "shift": 1,
                    "kind": "fixed_break_window",
                    "value": "13:00-13:30",
                    "params": {"paid": True, "enforcement": "warn", "min_minutes": 30},
                },
            )
        ],
        responses=ShiftRuleValidateResponseSerializer,
    )
    @action(detail=False, methods=["post"])
    def validate(self, request, company_id=None):
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        normalized = dict(ser.validated_data)
        shift = normalized.get("shift")
        if shift is not None:
            normalized["shift"] = getattr(shift, "id", shift)
        payload = {"valid": True, "normalized": normalized}
        return Response(ShiftRuleValidateResponseSerializer(payload).data)

class RosterViewSet(BasePolicyViewSet):
    queryset = RosterEntry.objects.select_related(
        "employee",
        "shift",
        "employee__department__branch__company",
        "employee__project__branch__company",
        "employee__trade_license__company",
    )
    serializer_class = RosterEntrySerializer
    filterset_class = RosterFilter
    ordering = ["date", "employee_id"]

    def perform_create(self, serializer):
        vd = serializer.validated_data
        is_h, was_h = holiday_flags(vd["employee"], vd["date"], vd.get("is_holiday"))
        serializer.save(is_holiday=is_h, was_holiday=was_h)

    def perform_update(self, serializer):
        inst = serializer.instance
        vd = serializer.validated_data
        emp = vd.get("employee", inst.employee)
        d = vd.get("date", inst.date)
        explicit = "is_holiday" in serializer.initial_data
        override = serializer.initial_data.get("is_holiday") if explicit else inst.is_holiday
        is_h, was_h = holiday_flags(emp, d, override if explicit else None)
        serializer.save(is_holiday=is_h, was_holiday=was_h)

    @extend_schema(
        description=(
            "Atomically upsert roster entries. Dates coinciding with calendar "
            "holidays are automatically flagged with `is_holiday`, and "
            "`was_holiday` records that a holiday was scheduled. Include "
            "`is_holiday` in an entry to explicitly override the default."
        ),
        examples=[
            OpenApiExample(
                "Upsert example",
                value={
                    "entries": [
                        {"employee": 1, "date": "2024-07-04", "shift": 1},
                        {
                            "employee": 1,
                            "date": "2024-07-05",
                            "shift": 1,
                            "is_holiday": False,
                        },
                    ]
                },
            )
        ],
        request=RosterBulkUpsertRequestSerializer,
        responses={200: RosterBulkUpsertResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="bulk-upsert")
    def bulk_upsert(self, request, company_id=None):
        req = RosterBulkUpsertRequestSerializer(data=request.data, context={"request": request})
        if not req.is_valid():
            return Response({"detail": "entries must be a non-empty list", "errors": req.errors}, status=400)
        validated = []
        for item, raw in zip(req.validated_data["entries"], req.initial_data["entries"]):
            item["is_holiday"], item["was_holiday"] = holiday_flags(
                item["employee"], item["date"], raw.get("is_holiday")
            )
            validated.append(item)
        allowed_emp_ids = set(scope_queryset(Employee.objects.all(), request.user).values_list("id", flat=True))
        allowed_shift_ids = set(scope_queryset(ShiftTemplate.objects.all(), request.user).values_list("id", flat=True))
        bad_emp = sorted({v["employee"].id for v in validated if v["employee"].id not in allowed_emp_ids})
        bad_shift = sorted({v["shift"].id for v in validated if v["shift"].id not in allowed_shift_ids})
        if bad_emp or bad_shift:
            return Response(
                {"detail": "Some items are outside your scope",
                 "errors": {"employee_ids": bad_emp, "shift_ids": bad_shift}},
                status=403,
            )
        to_create = [RosterEntry(**v) for v in validated]
        with transaction.atomic():
            RosterEntry.objects.bulk_create(
                to_create,
                update_conflicts=True,
                update_fields=[
                    "shift",
                    "override_start",
                    "override_end",
                    "is_rest_day",
                    "is_holiday",
                    "was_holiday",
                ],
                unique_fields=["employee", "date"],
            )
        payload = {"upserted": len(to_create)}
        return Response(RosterBulkUpsertResponseSerializer(payload).data, status=200)

    @extend_schema(
        description=(
            "Create or update consecutive roster entries starting from `start_date`."
            " Provide either `days` (number of days) or `until` (inclusive end date)."
            " `rest_weekdays` may list weekday codes such as ['SAT','SUN'] to mark"
            " rest days automatically. Entries on calendar holidays are flagged"
            " with `is_holiday`, and `was_holiday` records that a holiday was"
            " originally scheduled."
        ),
        examples=[
            OpenApiExample(
                "By days with weekend rest",
                value={
                    "employee": 1,
                    "shift": 1,
                    "start_date": "2024-07-01",
                    "days": 7,
                    "rest_weekdays": ["SAT", "SUN"],
                },
            ),
            OpenApiExample(
                "Multiple employees",
                value={
                    "employees": [1, 2],
                    "shift": 1,
                    "start_date": "2024-07-01",
                    "days": 3,
                },
            ),
            OpenApiExample(
                "Until date",
                value={
                    "employee": 1,
                    "shift": 1,
                    "start_date": "2024-07-01",
                    "until": "2024-07-31",
                },
            ),
            OpenApiExample(
                "Success response",
                value={"count": 31},
                response_only=True,
            ),
            OpenApiExample(
                "Accepted response",
                value={"task_id": "uuid"},
                response_only=True,
            ),
        ],
        request=RosterRangeSerializer,
        responses={
            200: OpenApiResponse(
                description="Count of roster entries created or updated",
                response=inline_serializer(
                    name="RosterRangeResult",
                    fields={"count": serializers.IntegerField()},
                ),
            ),
            202: OpenApiResponse(
                description="Task enqueued for asynchronous processing",
                response=inline_serializer(
                    name="RosterRangeTask",
                    fields={"task_id": serializers.CharField()},
                ),
            ),
        },
    )
    @action(detail=False, methods=["post"], url_path="schedule-range")
    def schedule_range(self, request, company_id=None):
        params = RosterRangeSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        params.is_valid(raise_exception=True)
        data = params.validated_data
        employees = list(data["employees"])

        allowed_emp_ids = set(
            scope_queryset(Employee.objects.all(), request.user).values_list("id", flat=True)
        )
        allowed_shift_ids = set(
            scope_queryset(ShiftTemplate.objects.all(), request.user).values_list("id", flat=True)
        )
        if (
            data["shift"].id not in allowed_shift_ids
            or any(e.id not in allowed_emp_ids for e in employees)
        ):
            return Response(
                {"detail": "Target employee/shift outside your scope", "errors": {}},
                status=403,
            )

        start = data["start_date"]
        end = (
            start + timedelta(days=data["days"] - 1)
            if data.get("days")
            else data["until"]
        )
        rest_weekdays = set(data.get("rest_weekdays", []))
        num_days = (end - start).days + 1
        if len(employees) > ASYNC_BULK_THRESHOLD:
            task = schedule_range_bulk.delay(
                [e.id for e in employees],
                data["shift"].id,
                start.isoformat(),
                end.isoformat(),
                list(rest_weekdays),
            )
            return Response({"task_id": task.id}, status=202)

        entries = []
        for emp in employees:
            for i in range(num_days):
                current = start + timedelta(days=i)
                weekday_code = [
                    "MON",
                    "TUE",
                    "WED",
                    "THU",
                    "FRI",
                    "SAT",
                    "SUN",
                ][current.weekday()]
                item = {
                    "employee": emp.id,
                    "date": current,
                    "shift": data["shift"].id,
                    "is_rest_day": weekday_code in rest_weekdays,
                }
                existing = RosterEntry.objects.filter(
                    employee=emp, date=current
                ).first()
                ser = self.get_serializer(instance=existing, data=item)
                ser.is_valid(raise_exception=True)
                v = ser.validated_data
                v["is_holiday"], v["was_holiday"] = holiday_flags(
                    v["employee"], v["date"], v.get("is_holiday")
                )
                entries.append(RosterEntry(**v))
        with transaction.atomic():
            RosterEntry.objects.bulk_create(
                entries,
                update_conflicts=True,
                update_fields=[
                    "shift",
                    "override_start",
                    "override_end",
                    "is_rest_day",
                    "is_holiday",
                    "was_holiday",
                ],
                unique_fields=["employee", "date"],
            )
        return Response({"count": len(entries)}, status=200)

    @extend_schema(
        description="Summarize roster entries grouped by employee, shift, or date.",
        parameters=[
            OpenApiParameter(
                "group_by",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["employee", "shift", "date"],
                description="Grouping field",
            )
        ],
        responses=RosterSummarySerializer(many=True),
    )
    @action(detail=False, methods=["get"])
    def summary(self, request, company_id=None):
        group_by = request.query_params.get("group_by", "employee")
        qs = self.filter_queryset(self.get_queryset())
        if group_by == "employee":
            data = (
                qs.values(
                    "employee",
                    "employee__first_name",
                    "employee__middle_name",
                    "employee__last_name",
                )
                .annotate(
                    days=Count("id"), rest_days=Count("id", filter=Q(is_rest_day=True))
                )
            )
        elif group_by == "shift":
            data = (
                qs.values("shift", "shift__name")
                .annotate(days=Count("id"), rest_days=Count("id", filter=Q(is_rest_day=True)))
            )
        else:
            data = (
                qs.values("date")
                .annotate(entries=Count("id"), rest_days=Count("id", filter=Q(is_rest_day=True)))
            )
        ser = RosterSummarySerializer(data, many=True)
        return Response(ser.data)

class LeaveTypeViewSet(BasePolicyViewSet):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    filterset_class = LeaveTypeFilter
    ordering = ["id"]
    search_fields = ["code", "name"]

document_filters(WorkCalendarViewSet)
document_filters(HolidayViewSet)
document_filters(ShiftTemplateViewSet)
document_filters(ShiftRuleViewSet)
document_filters(RosterViewSet)
document_filters(LeaveTypeViewSet)
