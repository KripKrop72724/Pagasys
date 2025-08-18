from django.db import models
from django.utils import timezone
from datetime import date, datetime, timedelta, timezone as dt_timezone
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.response import Response
from django.http import StreamingHttpResponse
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiExample
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.utils.dateparse import parse_datetime
import hmac
import hashlib
import csv
import io

from .permissions import CustomObjectPermission, GroupRequiredPermission
from .utils import scope_queryset, ensure_in_scope, employee_company_id
from .openapi_utils import document_filters
from .models_attendance import (
    Device,
    AttEvent,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    AttPair,
    AttDay,
    LeaveType,
    LeaveRequest,
    LeaveDay,
)
from .models import Employee
from .serializers_attendance import (
    DeviceSerializer,
    AttEventSerializer,
    WorkCalendarSerializer,
    HolidaySerializer,
    ShiftTemplateSerializer,
    ShiftRuleSerializer,
    RosterEntrySerializer,
    AttPairSerializer,
    AttDaySerializer,
    LeaveTypeSerializer,
    LeaveRequestSerializer,
    LeaveDaySerializer,
    AttEventIngestSerializer,
    AttEventIngestResponseSerializer,
)

MAX_SKEW = timedelta(minutes=10)


def _canonical_string(item: dict) -> bytes:
    ts = item["ts"]
    if hasattr(ts, "isoformat"):
        ts = ts.isoformat()
    return (
        f"{item['employee_id']}|{ts}|{item['direction']}|{item['device_id']}".encode("utf-8")
    )


def _shift_minutes_for_day(shift: ShiftTemplate, day: date) -> int:
    start_dt = datetime.combine(day, shift.start_time)
    end_dt = datetime.combine(day, shift.end_time)
    if shift.cross_midnight or end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return max(0, int((end_dt - start_dt).total_seconds() // 60) - (shift.break_minutes or 0))

DEFAULT_REQUIRED_GROUPS = [
    "Company Admin",
    "Branch Manager",
    "Payroll Manager",
    "Department Manager",
    "Project Manager",
    "Employee",
]


class DeviceViewSet(viewsets.ModelViewSet):
    queryset = Device.objects.all()
    serializer_class = DeviceSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["company", "name", "device_type"]
    ordering_fields = ["id", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class AttEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AttEvent.objects.all()
    serializer_class = AttEventSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {
        "employee": ["exact"],
        "company": ["exact"],
        "ts": ["date"],
        "device": ["exact"],
        "provider": ["exact"],
    }
    ordering_fields = ["ts"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class WorkCalendarViewSet(viewsets.ModelViewSet):
    queryset = WorkCalendar.objects.all()
    serializer_class = WorkCalendarSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["id", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class HolidayViewSet(viewsets.ModelViewSet):
    queryset = Holiday.objects.all()
    serializer_class = HolidaySerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["date", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class ShiftTemplateViewSet(viewsets.ModelViewSet):
    queryset = ShiftTemplate.objects.all()
    serializer_class = ShiftTemplateSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["id", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class ShiftRuleViewSet(viewsets.ModelViewSet):
    queryset = ShiftRule.objects.all()
    serializer_class = ShiftRuleSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["id", "shift", "kind"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class RosterEntryViewSet(viewsets.ModelViewSet):
    queryset = RosterEntry.objects.all()
    serializer_class = RosterEntrySerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = {
        "employee": ["exact"],
        "date": ["exact"],
        "shift": ["exact"],
    }
    ordering_fields = ["date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class AttPairViewSet(viewsets.ModelViewSet):
    queryset = AttPair.objects.all()
    serializer_class = AttPairSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["in_ts"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class AttDayFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lt")
    anomaly = filters.CharFilter(method="filter_anomaly")
    branch = filters.NumberFilter(method="filter_branch")

    class Meta:
        model = AttDay
        fields = ["employee", "status"]

    def filter_anomaly(self, queryset, name, value):
        return queryset.filter(**{"notes__has_key": value})

    def filter_branch(self, queryset, name, value):
        return queryset.filter(
            models.Q(employee__department__branch_id=value)
            | models.Q(employee__project__branch_id=value)
        )


class AttDayViewSet(viewsets.ModelViewSet):
    queryset = AttDay.objects.all()
    serializer_class = AttDaySerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = AttDayFilter
    ordering_fields = ["date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class LeaveTypeViewSet(viewsets.ModelViewSet):
    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["id", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class LeaveRequestFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="start_date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="end_date", lookup_expr="lte")

    class Meta:
        model = LeaveRequest
        fields = ["employee", "status"]


class LeaveRequestViewSet(viewsets.ModelViewSet):
    queryset = LeaveRequest.objects.all()
    serializer_class = LeaveRequestSerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = LeaveRequestFilter
    ordering_fields = ["start_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class LeaveDayViewSet(viewsets.ModelViewSet):
    queryset = LeaveDay.objects.all()
    serializer_class = LeaveDaySerializer
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


class AttEventIngestView(APIView):
    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    queryset = AttEvent.objects.all()

    @extend_schema(
        request=AttEventIngestSerializer(many=True),
        responses=AttEventIngestResponseSerializer,
        examples=[
            OpenApiExample(
                "Ingest Example",
                value=[
                    {
                        "employee_id": 1,
                        "ts": "2024-01-01T08:00:00Z",
                        "direction": "IN",
                        "device_id": 1,
                        "provider": "camera",
                        "confidence": "99.0",
                        "liveness": True,
                        "payload_sig": "abcdef",
                        "meta": {"source": "kiosk"},
                    }
                ],
                request_only=True,
            ),
            OpenApiExample(
                "Ingest Response",
                value={"created": 1, "duplicates": 0},
                response_only=True,
            ),
        ],
    )
    def post(self, request):
        data = request.data
        if not isinstance(data, list) or not data:
            raise ValidationError("Expected a non-empty JSON array")

        ser = AttEventIngestSerializer(data=data, many=True)
        ser.is_valid(raise_exception=True)
        items = ser.validated_data

        created = duplicates = 0

        for item in items:
            try:
                device = Device.objects.get(pk=item["device_id"], is_active=True)
            except Device.DoesNotExist:
                raise ValidationError({"device_id": "Unknown or inactive device"})

            expected = hmac.new(
                key=device.hmac_secret.encode("utf-8"),
                msg=_canonical_string(item),
                digestmod=hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, item["payload_sig"]):
                raise PermissionDenied("Invalid signature")

            employee = Employee.objects.select_related(
                "trade_license", "department__branch__company", "project__branch__company"
            ).get(pk=item["employee_id"])
            ensure_in_scope(employee, request.user, "employee")
            emp_co_id = employee_company_id(employee)
            if emp_co_id is None or (device.company_id and device.company_id != emp_co_id):
                raise PermissionDenied("Device/company mismatch for employee")

            ts = item["ts"]
            if isinstance(ts, str):
                ts = parse_datetime(ts)
            if ts is None or ts.tzinfo is None:
                raise ValidationError({"ts": "Timezone-aware ISO8601 required"})
            now_utc = datetime.now(dt_timezone.utc)
            if abs((ts.astimezone(dt_timezone.utc) - now_utc)) > MAX_SKEW:
                raise ValidationError({"ts": "Timestamp outside allowed skew"})

            ts_utc = ts.astimezone(dt_timezone.utc)
            try:
                _, created_flag = AttEvent.objects.get_or_create(
                    employee=employee,
                    ts=ts_utc,
                    device=device,
                    defaults={
                        "company_id": emp_co_id,
                        "direction": item["direction"],
                        "provider": item["provider"],
                        "face_conf": item.get("confidence"),
                        "liveness": item.get("liveness"),
                        "payload_sig": item["payload_sig"],
                        "meta": item.get("meta", {}),
                    },
                )
                if created_flag:
                    created += 1
                else:
                    duplicates += 1
            except Exception:
                duplicates += 1

        return Response({"created": created, "duplicates": duplicates}, status=status.HTTP_201_CREATED)


class RosterBulkView(APIView):
    """Bulk upsert roster entries via JSON or CSV."""

    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    queryset = RosterEntry.objects.all()

    @extend_schema(
        examples=[
            OpenApiExample(
                "Cross Midnight Roster",
                description="Assign a night shift that crosses midnight",
                value=[
                    {
                        "employee_id": 1,
                        "start_date": "2024-01-01",
                        "end_date": "2024-01-03",
                        "shift_id": 2,
                    }
                ],
                request_only=True,
            ),
            OpenApiExample(
                "Bulk Roster Response",
                value={"results": [{"row": 1, "status": "ok", "count": 3}]},
                response_only=True,
            ),
        ]
    )
    def post(self, request):
        if request.content_type and "csv" in request.content_type:
            text = request.body.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            data_list = list(reader)
        else:
            data_list = request.data if isinstance(request.data, list) else [request.data]

        results = []
        any_error = False
        for idx, row in enumerate(data_list, start=1):
            try:
                emp = Employee.objects.get(pk=row.get("employee_id"))
                ensure_in_scope(emp, request.user, "employee")
                shift = ShiftTemplate.objects.get(pk=row.get("shift_id"))
                ensure_in_scope(shift, request.user, "shift")
                emp_co_id = employee_company_id(emp)
                if emp_co_id is None or shift.company_id != emp_co_id:
                    raise ValueError("Employee and shift belong to different companies.")
                start = date.fromisoformat(row.get("start_date"))
                end = date.fromisoformat(row.get("end_date") or row.get("start_date"))
                if end < start:
                    raise ValueError("end_date before start_date")
            except Exception as exc:  # pragma: no cover - bad input
                results.append({"row": idx, "status": "error", "detail": str(exc)})
                any_error = True
                continue

            objs = [
                RosterEntry(employee=emp, date=start + timedelta(days=i), shift=shift)
                for i in range((end - start).days + 1)
            ]
            RosterEntry.objects.bulk_create(
                objs,
                update_conflicts=True,
                unique_fields=["employee", "date"],
                update_fields=["shift"],
            )
            results.append({"row": idx, "status": "ok", "count": len(objs)})

        status_code = status.HTTP_207_MULTI_STATUS if any_error else status.HTTP_200_OK
        return Response({"results": results}, status=status_code)


class TimesheetReportView(APIView):
    """Monthly timesheet summary per employee."""

    permission_classes = [
        IsAuthenticated,
        DjangoModelPermissions,
        GroupRequiredPermission,
        CustomObjectPermission,
    ]
    required_groups = DEFAULT_REQUIRED_GROUPS
    queryset = AttDay.objects.all()

    @extend_schema(
        examples=[
            OpenApiExample(
                "Missing OUT Punch",
                value={
                    "count": 1,
                    "results": [
                        {
                            "employee_id": 1,
                            "scheduled_minutes": 960,
                            "work_minutes": 300,
                            "late_minutes": 10,
                            "early_leave_minutes": 20,
                            "ot125_minutes": 30,
                            "ot150_minutes": 40,
                            "leave_minutes": {"Sick": 30},
                            "anomalies": 1,
                        }
                    ],
                },
                response_only=True,
            ),
            OpenApiExample(
                "Public Holiday OT",
                value={
                    "count": 1,
                    "results": [
                        {
                            "employee_id": 1,
                            "scheduled_minutes": 480,
                            "work_minutes": 0,
                            "ot150_minutes": 60,
                            "leave_minutes": {},
                            "anomalies": 0,
                        }
                    ],
                },
                response_only=True,
            ),
            OpenApiExample(
                "Partial Day Leave",
                value={
                    "count": 1,
                    "results": [
                        {
                            "employee_id": 1,
                            "scheduled_minutes": 480,
                            "work_minutes": 240,
                            "leave_minutes": {"Annual": 240},
                            "anomalies": 0,
                        }
                    ],
                },
                response_only=True,
            ),
        ]
    )
    def get(self, request):
        company_id = request.query_params.get("company")
        month_str = request.query_params.get("month")
        if not (company_id and month_str):
            return Response(
                {"detail": "company and month are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        start = datetime.strptime(month_str, "%Y-%m").date()
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)

        qs = Employee.objects.filter(
            models.Q(department__branch__company_id=company_id)
            | models.Q(project__branch__company_id=company_id)
            | models.Q(trade_license__company_id=company_id)
        ).filter(is_superuser=False)
        branch = request.query_params.get("branch")
        department = request.query_params.get("department")
        project = request.query_params.get("project")
        if branch:
            qs = qs.filter(models.Q(department__branch_id=branch) | models.Q(project__branch_id=branch))
        if department:
            qs = qs.filter(department_id=department)
        if project:
            qs = qs.filter(project_id=project)
        qs = scope_queryset(qs, request.user)

        paginator = PageNumberPagination()
        employees = paginator.paginate_queryset(qs, request, view=self)

        results = []
        leave_types = set()
        for emp in employees:
            roster = (
                RosterEntry.objects
                .filter(employee=emp, date__gte=start, date__lt=end)
                .select_related("shift")
            )
            leave_by_date = {}
            for ld in LeaveDay.objects.filter(
                request__employee=emp,
                date__gte=start,
                date__lt=end,
                request__status="approved",
            ).select_related("request__leave_type"):
                leave_by_date.setdefault(ld.date, []).append(ld)

            sched = 0
            for r in roster:
                mins = _shift_minutes_for_day(r.shift, r.date)
                if r.date in leave_by_date:
                    mins = max(0, mins - sum(ld.minutes for ld in leave_by_date[r.date]))
                sched += mins

            days_qs = AttDay.objects.filter(employee=emp, date__gte=start, date__lt=end)
            work = late = early = ot125 = ot150 = 0
            for day in days_qs:
                work += day.work_minutes
                late += day.late_minutes
                early += day.early_leave_minutes
                ot125 += day.ot125_minutes
                ot150 += day.ot150_minutes

            pairs_anom = (
                AttPair.objects.filter(
                    employee=emp,
                    in_ts__date__gte=start,
                    in_ts__date__lt=end,
                )
                .exclude(quality="ok")
                .values("in_ts__date")
                .distinct()
                .count()
            )
            day_anom = (
                days_qs.filter(
                    models.Q(status="missing") | ~models.Q(notes={})
                )
                .values("date")
                .distinct()
                .count()
            )
            anomalies = max(pairs_anom, day_anom)

            leave_dict = {}
            for lds in leave_by_date.values():
                for ld in lds:
                    lt_name = ld.request.leave_type.name
                    minutes = int(ld.minutes * ld.get_pay_percent() / 100)
                    leave_dict[lt_name] = leave_dict.get(lt_name, 0) + minutes
                    leave_types.add(lt_name)
            results.append(
                {
                    "employee_id": emp.id,
                    "employee": str(emp),
                    "scheduled_minutes": sched,
                    "work_minutes": work,
                    "late_minutes": late,
                    "early_leave_minutes": early,
                    "ot125_minutes": ot125,
                    "ot150_minutes": ot150,
                    "leave_minutes": leave_dict,
                    "anomalies": anomalies,
                }
            )

        if request.query_params.get("export") == "csv":
            header = [
                "employee_id",
                "employee",
                "scheduled_minutes",
                "work_minutes",
                "late_minutes",
                "early_leave_minutes",
                "ot125_minutes",
                "ot150_minutes",
                "anomalies",
            ] + sorted(leave_types)

            class Echo:
                def write(self, value):
                    return value

            def row_iter():
                writer = csv.writer(Echo())
                yield writer.writerow(header)
                for res in results:
                    row = [
                        res["employee_id"],
                        res["employee"],
                        res["scheduled_minutes"],
                        res["work_minutes"],
                        res["late_minutes"],
                        res["early_leave_minutes"],
                        res["ot125_minutes"],
                        res["ot150_minutes"],
                        res["anomalies"],
                    ]
                    for lt in sorted(leave_types):
                        row.append(res["leave_minutes"].get(lt, 0))
                    yield writer.writerow(row)

            response = StreamingHttpResponse(row_iter(), content_type="text/csv")
            response["Content-Disposition"] = "attachment; filename=timesheet.csv"
            return response

        return paginator.get_paginated_response(results)


# Attach filter documentation
for _vs in [
    DeviceViewSet,
    AttEventViewSet,
    WorkCalendarViewSet,
    HolidayViewSet,
    ShiftTemplateViewSet,
    ShiftRuleViewSet,
    RosterEntryViewSet,
    AttPairViewSet,
    AttDayViewSet,
    LeaveTypeViewSet,
    LeaveRequestViewSet,
    LeaveDayViewSet,
]:
    document_filters(_vs)
