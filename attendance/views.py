import calendar
from datetime import date, timedelta

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.exceptions import NotFound
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.db.models import CharField, Q, Value
from django.db.models.functions import Coalesce
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from pagasys.openapi_utils import document_filters
from pagasys.utils import scope_queryset
from pagasys.models import Employee, Company, Branch, Department, Project
from pagasys.pagination import AllRecordsMixin
from django.http import HttpResponse

from .models import AttDay, AttPair, AttAdjustment
from .services import build_monthly_calendar
from .reports import (
    get_late_comers,
    group_late_comers,
    render_late_comers_pdf,
    render_monthly_attendance_pdf,
)
from .serializers import (
    AttDaySerializer,
    AttPairSerializer,
    ManualAttPairSerializer,
    RecomputeRangeSerializer,
    LockDaysSerializer,
    AttAdjustmentSerializer,
)
from .filters import AttDayFilter, AttPairFilter
from .tasks import (
    recompute_range_task,
    pair_employee_day_task,
    compute_employee_day_task,
)

MAX_RANGE_DAYS = 31
MAX_EMPLOYEES = 50
CALENDAR_PAGE_SIZE = 200
class AttendanceCalendarMetricsDocSerializer(serializers.Serializer):
    work_min = serializers.IntegerField(help_text="Computed work minutes for the day")
    unpaid_break_min = serializers.IntegerField(help_text="Unpaid break minutes deducted")
    paid_break_min = serializers.IntegerField(help_text="Paid break minutes")
    late_min = serializers.IntegerField(help_text="Minutes late relative to shift start")
    early_leave_min = serializers.IntegerField(help_text="Minutes left before scheduled end")
    ot_regular_min = serializers.IntegerField(help_text="Regular overtime minutes")
    ot_night_min = serializers.IntegerField(help_text="Night overtime minutes")
    ot_holiday_min = serializers.IntegerField(help_text="Holiday overtime minutes")
    on_leave = serializers.BooleanField(help_text="True when the employee was on leave")
    leave_portion = serializers.FloatField(help_text="Portion of the day covered by leave")
    is_holiday = serializers.BooleanField(help_text="Day is marked as a holiday")
    is_rest_day = serializers.BooleanField(help_text="Day is marked as a rest day")
    pairs_count = serializers.IntegerField(help_text="Number of raw IN/OUT pairs recorded")
    punches_used = serializers.IntegerField(help_text="Punch events contributing to computation")


class AttendanceCalendarRowDocSerializer(serializers.Serializer):
    date = serializers.DateField(format="iso-8601", help_text="Day within the requested month")
    status = serializers.CharField(
        allow_null=True,
        help_text="Canonical attendance status (present, absent, leave, rest, holiday, partial)",
    )
    locked = serializers.BooleanField(help_text="Whether the day is locked for changes")
    locked_reason = serializers.CharField(
        allow_null=True,
        help_text="Message explaining why adjustments are blocked when locked",
    )
    metrics = AttendanceCalendarMetricsDocSerializer()
    anomalies = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Counts keyed by canonical anomaly name",
    )
    pairs = AttPairSerializer(many=True, required=False, read_only=True)
    adjustments = AttAdjustmentSerializer(many=True, required=False, read_only=True)


class AttendanceCalendarSummaryDocSerializer(serializers.Serializer):
    present = serializers.IntegerField(help_text="Number of present days in the month")
    absent = serializers.IntegerField(help_text="Number of absent days in the month")
    leave = serializers.IntegerField(help_text="Number of leave days in the month")
    holiday = serializers.IntegerField(help_text="Number of holiday days in the month")
    rest = serializers.IntegerField(help_text="Number of rest days in the month")
    partial = serializers.IntegerField(help_text="Number of partial/exception days in the month")
    locked_days = serializers.IntegerField(help_text="Count of days locked for changes")
    total_ot_min = serializers.IntegerField(help_text="Total overtime minutes in the month")


class AttendanceCalendarEmployeeMetadataDocSerializer(serializers.Serializer):
    department = serializers.CharField(allow_null=True, required=False)
    project = serializers.CharField(allow_null=True, required=False)
    branch = serializers.CharField(allow_null=True, required=False)
    code = serializers.CharField(help_text="Employee code/username")


class AttendanceCalendarEmployeeDocSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display = serializers.CharField(help_text="Display name shown to the user")
    metadata = AttendanceCalendarEmployeeMetadataDocSerializer()
    rows = AttendanceCalendarRowDocSerializer(many=True, required=False)
    summary = AttendanceCalendarSummaryDocSerializer()


class AttendanceCalendarResponseDocSerializer(serializers.Serializer):
    month = serializers.CharField(help_text="Requested month in YYYY-MM format")
    days = serializers.ListField(
        child=serializers.DateField(format="iso-8601"),
        help_text="Ordered list of days that frame the calendar grid",
    )
    employees = AttendanceCalendarEmployeeDocSerializer(many=True)
    next = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Cursor to fetch the next page of employees when paginated",
    )
    previous = serializers.CharField(
        allow_null=True,
        required=False,
        help_text="Cursor to fetch the previous page of employees",
    )

ATTENDANCE_CALENDAR_QUERY_PARAMS = [
    OpenApiParameter(
        "month",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        required=True,
        description=(
            "Target month in YYYY-MM format. The API expands this to the first and last day "
            "of the month to guarantee a 28–31 day window."
        ),
        examples=[OpenApiExample("May 2024", value="2024-05")],
    ),
    OpenApiParameter(
        "include_pairs",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="When true, embed AttPair records for each populated day",
        examples=[OpenApiExample("Include pairs", value="true")],
    ),
    OpenApiParameter(
        "include_adjustments",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="When true, embed AttAdjustment records that land on the day",
        examples=[OpenApiExample("Include adjustments", value="true")],
    ),
    OpenApiParameter(
        "include_anomalies",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="Toggle anomaly payloads on day rows. Defaults to true.",
        examples=[OpenApiExample("Omit anomalies", value="false")],
    ),
    OpenApiParameter(
        "stats_only",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="Return only monthly summaries without the per-day grid",
        examples=[OpenApiExample("Stats only", value="true")],
    ),
    OpenApiParameter(
        "status",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description=(
            "Comma separated list of AttDay.status values to include (e.g. present,absent,leave). "
            "Only matching days appear in the grid and summary counts."
        ),
    ),
    OpenApiParameter(
        "locked",
        OpenApiTypes.BOOL,
        OpenApiParameter.QUERY,
        description="Filter days by lock state before aggregation",
    ),
    OpenApiParameter(
        "employee",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description=(
            "Restrict the calendar to specific employees. Accepts repeated parameters or a comma "
            "separated list of employee IDs."
        ),
    ),
    OpenApiParameter(
        "branch",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description=(
            "Restrict employees by branch via their department or project relationship. Accepts "
            "repeated parameters or a comma separated list of branch IDs."
        ),
    ),
    OpenApiParameter(
        "department",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description="Restrict employees by department IDs (repeated or comma separated)",
    ),
    OpenApiParameter(
        "project",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description="Restrict employees by project IDs (repeated or comma separated)",
    ),
    OpenApiParameter(
        "search",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description=(
            "Case-insensitive text search over employee first name, last name, username, email, "
            "department name, project name, and related branch names. All terms supplied must match."
        ),
        examples=[OpenApiExample("Find Alice", value="alice ops")],
    ),
    OpenApiParameter(
        "sort",
        OpenApiTypes.STR,
        OpenApiParameter.QUERY,
        description=(
            "Comma separated list of fields to order employees by. Supports name, code, department, "
            "project, first_name, last_name, and id. Prefix with '-' for descending order."
        ),
        examples=[OpenApiExample("Department then name", value="department,-name")],
    ),
]

MONTHLY_REPORT_QUERY_PARAMS = [
    param
    for param in ATTENDANCE_CALENDAR_QUERY_PARAMS
    if param.name
    in {"month", "employee", "branch", "department", "project", "status", "locked"}
]

ATTENDANCE_CALENDAR_EXAMPLE = OpenApiExample(
    "Calendar grid",
    value={
        "month": "2024-05",
        "days": ["2024-05-01", "2024-05-02", "2024-05-03"],
        "employees": [
            {
                "id": 17,
                "display": "Maria Gomez",
                "metadata": {
                    "department": "Operations",
                    "project": "Project Falcon",
                    "branch": "Dubai Marina",
                    "code": "EMP-0017",
                },
                "rows": [
                    {
                        "date": "2024-05-01",
                        "status": "present",
                        "locked": True,
                        "locked_reason": "Attendance day is locked; adjustments are disabled.",
                        "metrics": {
                            "work_min": 480,
                            "unpaid_break_min": 0,
                            "paid_break_min": 60,
                            "late_min": 5,
                            "early_leave_min": 0,
                            "ot_regular_min": 45,
                            "ot_night_min": 0,
                            "ot_holiday_min": 0,
                            "on_leave": False,
                            "leave_portion": 0.0,
                            "is_holiday": False,
                            "is_rest_day": False,
                            "pairs_count": 2,
                            "punches_used": 4,
                        },
                        "anomalies": {"missing_out_closed_at_next_in": 1},
                        "adjustments": [
                            {
                                "id": 901,
                                "employee": 17,
                                "date": "2024-05-01",
                                "delta_work_min": -15,
                                "reason": "Late arrival waiver",
                                "created_by_id": 3,
                                "created_at": "2024-05-02T06:00:00Z",
                            }
                        ],
                        "pairs": [
                            {
                                "id": 3001,
                                "employee": 17,
                                "date": "2024-05-01",
                                "in_event_id": 555,
                                "out_event_id": 556,
                                "in_ts": "2024-05-01T08:00:00+04:00",
                                "out_ts": "2024-05-01T12:00:00+04:00",
                                "duration_min": 240,
                                "cross_midnight": False,
                                "source": "auto",
                                "anomaly": {},
                            }
                        ],
                    }
                ],
                "summary": {
                    "present": 18,
                    "absent": 2,
                    "leave": 1,
                    "holiday": 1,
                    "rest": 3,
                    "partial": 0,
                    "locked_days": 12,
                    "total_ot_min": 480,
                },
            }
        ],
        "next": None,
        "previous": None,
    },
    response_only=True,
)


class AttendanceCalendarPagination(AllRecordsMixin, CursorPagination):
    page_size = CALENDAR_PAGE_SIZE
    ordering = ("first_name", "last_name", "username", "id")

    def get_ordering(self, request, queryset, view):  # pragma: no cover - simple delegation
        if getattr(view, "cursor_ordering", None):
            return tuple(view.cursor_ordering)
        return super().get_ordering(request, queryset, view)


def parse_month(value: str):
    if not value:
        raise serializers.ValidationError({"month": "Expected YYYY-MM query parameter"})
    try:
        year, month = value.split("-")
        start = date(int(year), int(month), 1)
    except (TypeError, ValueError):
        raise serializers.ValidationError({"month": "Expected YYYY-MM format"})
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    end = start.replace(day=days_in_month)
    return start, end


def parse_bool(value, *, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    value = value.lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise serializers.ValidationError({"detail": f"Invalid boolean value '{value}'"})


def parse_int_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        items = str(value).split(",")
    result = []
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError as exc:
            raise serializers.ValidationError({"detail": f"Invalid integer '{item}'"}) from exc
    return result


class LateComersPDFRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class MonthlyAttendancePDFRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


@extend_schema_view(
    list=extend_schema(
        description=(
            "List computed attendance days. Supports filtering by employee, date,"
            " status, holiday flags, lock state, and branch." 
        ),
        examples=[
            OpenApiExample(
                "IN-AUTO-OUT request",
                value={"employee": 1, "date": "2024-01-01"},
                request_only=True,
            ),
            OpenApiExample(
                "Filter by branch",
                value={"branch": "7"},
                request_only=True,
            ),
            OpenApiExample(
                "IN-AUTO-OUT response",
                value=[
                    {
                        "id": 1,
                        "employee": 1,
                        "date": "2024-01-01",
                        "work_min": 480,
                        "anomalies": {},
                    }
                ],
                response_only=True,
            ),
            OpenApiExample(
                "Duplicate IN request",
                value={"employee": 1, "date": "2024-01-02"},
                request_only=True,
            ),
            OpenApiExample(
                "Duplicate IN response",
                value=[
                    {
                        "id": 2,
                        "employee": 1,
                        "date": "2024-01-02",
                        "work_min": 60,
                        "anomalies": {"missing_out_closed_at_next_in": 1},
                    }
                ],
                response_only=True,
            ),
        ],
    ),
    retrieve=extend_schema(description="Retrieve a single computed attendance day."),
)
@extend_schema(
    tags=["Attendance"],
    description="Read-only access to canonical daily attendance results.",
)
class AttDayViewSet(viewsets.ReadOnlyModelViewSet):
    """Expose computed daily attendance summaries."""

    queryset = AttDay.objects.all().select_related("employee", "shift", "roster")
    serializer_class = AttDaySerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AttDayFilter

    def get_queryset(self):
        """Restrict results to the requesting user's scope."""
        return scope_queryset(super().get_queryset(), self.request.user)

    @extend_schema(
        description=(
            "Queue recomputation for a date range and optional employees."
            f" Range limited to {MAX_RANGE_DAYS} days and {MAX_EMPLOYEES} employees."
            " Dates must be supplied in YYYY-MM-DD and interpreted in the"
            " company's timezone."
        ),
        request=RecomputeRangeSerializer,
        responses={
            200: OpenApiResponse(
                description="Recompute task queued",
                response=inline_serializer(
                    name="RecomputeResponse",
                    fields={"queued": serializers.BooleanField()},
                ),
            )
        },
        examples=[
            OpenApiExample(
                "Recompute range",
                value={
                    "employee_ids": [1, 2],
                    "start": "2024-01-01",
                    "end": "2024-01-07",
                },
            )
        ],
    )
    @action(detail=False, methods=["post"], url_path="recompute")
    def recompute(self, request):
        params = RecomputeRangeSerializer(data=request.data or {})
        params.is_valid(raise_exception=True)
        data = params.validated_data
        recompute_range_task.delay(
            data.get("employee_ids", []), data["start"].isoformat(), data["end"].isoformat()
        )
        return Response({"queued": True})

    @extend_schema(
        description=(
            "Lock or unlock attendance days within a date range."
            " Dates are expected in YYYY-MM-DD and evaluated in the"
            " company timezone."
        ),
        request=LockDaysSerializer,
        responses={
            200: OpenApiResponse(
                description="Count of records updated",
                response=inline_serializer(
                    name="LockResponse",
                    fields={"updated": serializers.IntegerField()},
                ),
            )
        },
        examples=[
            OpenApiExample(
                "Lock days",
                value={
                    "employee_ids": [1],
                    "start": "2024-01-01",
                    "end": "2024-01-07",
                    "locked": True,
                },
            )
        ],
    )
    @action(detail=False, methods=["post"], url_path="lock")
    def lock(self, request):
        params = LockDaysSerializer(data=request.data or {})
        params.is_valid(raise_exception=True)
        data = params.validated_data
        start, end = data["start"], data["end"]
        eids = data.get("employee_ids", [])
        qs = self.get_queryset().filter(date__range=(start, end))
        if eids:
            qs = qs.filter(employee_id__in=eids)
        with transaction.atomic():
            qs.update(locked=data.get("locked", True))
        return Response({"updated": qs.count()})

    @extend_schema(
        description="Render a PDF report of late arrivals.",
        parameters=[
            OpenApiParameter(
                name="start",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Inclusive start date in YYYY-MM-DD.",
            ),
            OpenApiParameter(
                name="end",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Inclusive end date in YYYY-MM-DD.",
            ),
            OpenApiParameter(
                name="branch",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional branch ID filter.",
            ),
            OpenApiParameter(
                name="department",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional department ID filter.",
            ),
            OpenApiParameter(
                name="project",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional project ID filter.",
            ),
            OpenApiParameter(
                name="shift",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description="Optional shift template ID filter.",
            ),
        ],
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="PDF report of late comers.",
            )
        },
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="late-comers-report",
        permission_classes=[IsAdminUser],
        renderer_classes=[LateComersPDFRenderer],
    )
    def late_comers_report(self, request, company_id=None):
        """Render a PDF report of late arrivals."""

        try:
            start = date.fromisoformat(request.query_params.get("start"))
            end = date.fromisoformat(request.query_params.get("end"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "start and end query params required in YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        filters = {}
        for key in ["branch", "department", "project", "shift"]:
            val = request.query_params.get(key)
            if val:
                filters[f"{key}_id"] = int(val)
        records = get_late_comers(start, end, filters)
        branches, stats = group_late_comers(records)
        pdf = render_late_comers_pdf(branches, stats, start, end, request)
        filename = f"late_comers_{start}_{end}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response



@extend_schema_view(
    list=extend_schema(
        description=(
            "List paired IN/OUT sessions. An 'auto' punch opens a new session when"
            " none is active or closes the current session. Supports filtering by"
            " employee, date, source, and branch."
        ),
    ),
    retrieve=extend_schema(
        description="Retrieve a specific paired session and its anomalies.",
    ),
    create=extend_schema(
        description=(
            "Create a manual attendance pair and recompute the day."
            " `in_ts` and `out_ts` must be full ISO-8601 timestamps"
            " including timezone offsets."
        ),
        request=ManualAttPairSerializer,
        responses={201: AttPairSerializer},
        examples=[
            OpenApiExample(
                "Manual pair request",
                value={
                    "employee": 1,
                    "date": "2024-01-01",
                    "in_ts": "2024-01-01T08:00:00+04:00",
                    "out_ts": "2024-01-01T17:00:00+04:00",
                },
            ),
            OpenApiExample(
                "Manual pair response",
                value={
                    "id": 99,
                    "employee": 1,
                    "date": "2024-01-01",
                    "in_event_id": -1,
                    "out_event_id": None,
                    "in_ts": "2024-01-01T08:00:00+04:00",
                    "out_ts": "2024-01-01T17:00:00+04:00",
                    "duration_min": 540,
                    "cross_midnight": False,
                    "source": "manual",
                    "anomaly": {},
                },
                response_only=True,
            ),
        ],
    ),
)
@extend_schema(
    tags=["Attendance"],
    description=(
        "Review and manage paired punch sessions used for computation. 'auto'"
        " punches toggle sessions, and anomalies such as"
        " 'missing_out_closed_at_next_in' indicate irregular sequences."
    ),
)
class AttPairViewSet(viewsets.ModelViewSet):
    """Access and manually create paired IN/OUT punches."""

    queryset = AttPair.objects.all().select_related("employee")
    serializer_class = AttPairSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_class = AttPairFilter

    def get_queryset(self):
        """Restrict results to the requesting user's scope."""
        return scope_queryset(super().get_queryset(), self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return ManualAttPairSerializer
        return super().get_serializer_class()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pair = serializer.save()
        from .services import compute_att_day

        compute_att_day(pair.employee_id, pair.date)
        output = AttPairSerializer(pair, context=self.get_serializer_context())
        headers = self.get_success_headers(output.data)
        return Response(output.data, status=status.HTTP_201_CREATED, headers=headers)

    @extend_schema(
        description=(
            "Rebuild pairs and recompute days for a date range. "
            f"Range limited to {MAX_RANGE_DAYS} days and {MAX_EMPLOYEES} employees."
        ),
        request=RecomputeRangeSerializer,
        responses={
            200: OpenApiResponse(
                description="Tasks queued",
                response=inline_serializer(
                    name="RebuildResponse",
                    fields={"queued": serializers.IntegerField()},
                ),
            )
        },
    )
    @action(detail=False, methods=["post"], url_path="rebuild")
    def rebuild(self, request, *args, **kwargs):
        params = RecomputeRangeSerializer(data=request.data or {})
        params.is_valid(raise_exception=True)
        data = params.validated_data
        start, end = data["start"], data["end"]
        if end < start or (end - start).days > MAX_RANGE_DAYS:
            raise serializers.ValidationError("Date range too large")
        ids = data.get("employee_ids") or []
        qs = (
            Employee.objects.filter(id__in=ids)
            if ids
            else Employee.objects.filter(is_active=True)
        )
        eids = list(qs.values_list("id", flat=True)[:MAX_EMPLOYEES])
        if not eids:
            raise serializers.ValidationError("No valid employees")
        queued = 0
        cur = start
        while cur <= end:
            for eid in eids:
                day_iso = cur.isoformat()
                pair_employee_day_task.delay(eid, day_iso)
                compute_employee_day_task.delay(eid, day_iso)
                queued += 1
            cur += timedelta(days=1)
        return Response({"queued": queued})


# attach filter documentation
document_filters(AttDayViewSet)
document_filters(AttPairViewSet)


@extend_schema_view(
    list=extend_schema(
        summary="List attendance calendar rows",
        description=(
            "Aggregate AttDay outcomes, optional AttPair sessions, and AttAdjustment entries into "
            "a month-oriented matrix optimised for calendar widgets. The endpoint enforces scope "
            "permissions identical to the AttDay and AttPair APIs, supports cursor pagination "
            "for large employee sets, and exposes optional expansions so clients can trade payload "
            "size for detail."
        ),
        parameters=ATTENDANCE_CALENDAR_QUERY_PARAMS,
        responses={
            200: OpenApiResponse(
                description="Monthly attendance grid with optional drill-down detail",
                response=AttendanceCalendarResponseDocSerializer,
            )
        },
        examples=[ATTENDANCE_CALENDAR_EXAMPLE],
    ),
    retrieve=extend_schema(
        summary="Retrieve calendar rows for a single employee",
        description=(
            "Return the same calendar payload as the list view but scoped to the employee identified "
            "by the path parameter. Supports the same query parameters (month, include_* flags, "
            "status, locked, search, etc.) so UI drill-down panels can reuse list view requests."
        ),
        parameters=ATTENDANCE_CALENDAR_QUERY_PARAMS,
        responses={
            200: OpenApiResponse(
                description="Single-employee attendance calendar response",
                response=AttendanceCalendarResponseDocSerializer,
            )
        },
        examples=[ATTENDANCE_CALENDAR_EXAMPLE],
    ),
)
@extend_schema(
    tags=["Attendance"],
    description=(
        "Monthly attendance calendar endpoint that aggregates computed AttDay summaries, raw "
        "pairs, and manual adjustments for each employee in scope. Use the optional lock and "
        "adjustment actions to manage period finalisation without leaving the calendar view."
    ),
)
class AttendanceCalendarViewSet(viewsets.GenericViewSet):
    """Expose a monthly attendance calendar grid combining days, pairs and adjustments."""

    queryset = Employee.objects.all()
    pagination_class = AttendanceCalendarPagination
    filter_backends = []
    serializer_class = AttendanceCalendarResponseDocSerializer

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related(
                "department__branch",
                "project__branch",
                "trade_license__company",
            )
        )
        return scope_queryset(qs, self.request.user)

    def _filter_employees(self, queryset, request, company_id):
        queryset = queryset.filter(is_superuser=False)
        if company_id:
            queryset = queryset.filter(
                Q(trade_license__company_id=company_id)
                | Q(department__branch__company_id=company_id)
                | Q(project__branch__company_id=company_id)
            )

        employee_ids = parse_int_list(request.query_params.getlist("employee"))
        if employee_ids:
            queryset = queryset.filter(id__in=employee_ids)

        branch_ids = parse_int_list(request.query_params.getlist("branch"))
        if branch_ids:
            branch_filter = Q()
            for branch_id in branch_ids:
                branch_filter |= Q(department__branch_id=branch_id)
                branch_filter |= Q(project__branch_id=branch_id)
            queryset = queryset.filter(branch_filter)

        department_ids = parse_int_list(request.query_params.getlist("department"))
        if department_ids:
            queryset = queryset.filter(department_id__in=department_ids)

        project_ids = parse_int_list(request.query_params.getlist("project"))
        if project_ids:
            queryset = queryset.filter(project_id__in=project_ids)

        search_value = request.query_params.get("search", "").strip()
        if search_value:
            terms = [term for term in search_value.split() if term]
            for term in terms:
                term_filter = (
                    Q(first_name__icontains=term)
                    | Q(last_name__icontains=term)
                    | Q(username__icontains=term)
                    | Q(email__icontains=term)
                    | Q(department__name__icontains=term)
                    | Q(project__name__icontains=term)
                    | Q(department__branch__name__icontains=term)
                    | Q(project__branch__name__icontains=term)
                )
                queryset = queryset.filter(term_filter)

        return queryset.distinct()

    def _apply_sorting(self, queryset, request):
        sort_param = request.query_params.get("sort", "").strip()
        annotations = {}
        ordering = []

        field_map = {
            "name": ["first_name", "last_name", "username"],
            "first_name": ["first_name"],
            "last_name": ["last_name"],
            "code": ["username"],
            "department": ["department_name"],
            "project": ["project_name"],
            "id": ["id"],
        }

        def ensure_annotation(key):
            if key == "department_name" and "department_name" not in annotations:
                annotations["department_name"] = Coalesce(
                    "department__name",
                    Value(""),
                    output_field=CharField(),
                )
            if key == "project_name" and "project_name" not in annotations:
                annotations["project_name"] = Coalesce(
                    "project__name",
                    Value(""),
                    output_field=CharField(),
                )

        if sort_param:
            for raw in sort_param.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                descending = raw.startswith("-")
                key = raw[1:] if descending else raw
                mapped = field_map.get(key)
                if not mapped:
                    continue
                for field_name in mapped:
                    ensure_annotation(field_name)
                    clause = field_name
                    if descending:
                        clause = f"-{clause}"
                    ordering.append(clause)

        if not ordering:
            ordering = ["first_name", "last_name", "username"]

        if not any(field.lstrip("-") == "id" for field in ordering):
            ordering.append("id")

        if annotations:
            queryset = queryset.annotate(**annotations)

        self.cursor_ordering = ordering
        return queryset

    def _summarise_report_filters(self, request, company_id, status_filters, locked_filter):
        summary = {
            "branch": [],
            "department": [],
            "project": [],
            "status": [],
            "locked": "",
        }

        branch_ids = parse_int_list(request.query_params.getlist("branch"))
        if branch_ids:
            branch_qs = Branch.objects.filter(id__in=branch_ids)
            if company_id:
                branch_qs = branch_qs.filter(company_id=company_id)
            branch_qs = scope_queryset(branch_qs, request.user)
            summary["branch"] = list(branch_qs.order_by("name").values_list("name", flat=True))

        department_ids = parse_int_list(request.query_params.getlist("department"))
        if department_ids:
            dept_qs = Department.objects.filter(id__in=department_ids)
            if company_id:
                dept_qs = dept_qs.filter(branch__company_id=company_id)
            dept_qs = scope_queryset(dept_qs, request.user)
            summary["department"] = list(
                dept_qs.order_by("name").values_list("name", flat=True)
            )

        project_ids = parse_int_list(request.query_params.getlist("project"))
        if project_ids:
            project_qs = Project.objects.filter(id__in=project_ids)
            if company_id:
                project_qs = project_qs.filter(branch__company_id=company_id)
            project_qs = scope_queryset(project_qs, request.user)
            summary["project"] = list(
                project_qs.order_by("name").values_list("name", flat=True)
            )

        status_labels = dict(AttDay._meta.get_field("status").choices)
        if status_filters:
            summary["status"] = [status_labels.get(code, code) for code in status_filters]

        if locked_filter is True:
            summary["locked"] = "Locked only"
        elif locked_filter is False:
            summary["locked"] = "Unlocked only"

        return summary


    def list(self, request, company_id=None):
        start, end = parse_month(request.query_params.get("month"))
        include_pairs = parse_bool(request.query_params.get("include_pairs"), default=False)
        include_adjustments = parse_bool(
            request.query_params.get("include_adjustments"), default=False
        )
        include_anomalies = parse_bool(
            request.query_params.get("include_anomalies"), default=True
        )
        stats_only = parse_bool(request.query_params.get("stats_only"), default=False)

        status_param = request.query_params.get("status")
        status_filters = (
            [value.strip() for value in status_param.split(",") if value.strip()]
            if status_param
            else []
        )
        locked_filter = None
        if "locked" in request.query_params:
            locked_filter = parse_bool(request.query_params.get("locked"))

        queryset = self._filter_employees(self.get_queryset(), request, company_id)
        queryset = self._apply_sorting(queryset, request)

        page = self.paginate_queryset(queryset)
        paginator = getattr(self, "paginator", None)
        all_requested = bool(getattr(paginator, "all_requested", False)) if paginator else False

        if page is not None:
            employees = list(page)
        elif all_requested:
            employees = list(queryset)
        else:
            employees = list(queryset[:CALENDAR_PAGE_SIZE])
            if len(employees) > CALENDAR_PAGE_SIZE:
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
            serializer_context=self.get_serializer_context(),
        )
        payload = calendar_result["payload"]

        if getattr(self, "paginator", None) and getattr(self.paginator, "page", None) is not None:
            payload["next"] = self.paginator.get_next_link()
            payload["previous"] = self.paginator.get_previous_link()
        return Response(payload)

    def retrieve(self, request, pk=None, company_id=None):
        start, end = parse_month(request.query_params.get("month"))
        include_pairs = parse_bool(request.query_params.get("include_pairs"), default=False)
        include_adjustments = parse_bool(
            request.query_params.get("include_adjustments"), default=False
        )
        include_anomalies = parse_bool(
            request.query_params.get("include_anomalies"), default=True
        )
        stats_only = parse_bool(request.query_params.get("stats_only"), default=False)

        status_param = request.query_params.get("status")
        status_filters = (
            [value.strip() for value in status_param.split(",") if value.strip()]
            if status_param
            else []
        )
        locked_filter = None
        if "locked" in request.query_params:
            locked_filter = parse_bool(request.query_params.get("locked"))

        queryset = self._filter_employees(self.get_queryset(), request, company_id)
        queryset = self._apply_sorting(queryset, request)
        employee = queryset.filter(pk=pk).first()
        if not employee:
            raise NotFound("Employee not found")

        calendar_result = build_monthly_calendar(
            [employee],
            (start, end),
            user=request.user,
            include_pairs=include_pairs,
            include_adjustments=include_adjustments,
            include_anomalies=include_anomalies,
            stats_only=stats_only,
            status_filters=status_filters,
            locked_filter=locked_filter,
            serializer_context=self.get_serializer_context(),
        )
        payload = calendar_result["payload"]
        return Response(payload)

    @extend_schema(
        summary="Download a monthly attendance PDF report",
        description=(
            "Generate a landscape PDF that groups employees by branch and renders a day-by-day "
            "attendance grid using compact glyphs. The report honours the same filtering options "
            "as the calendar API (branch, department, project, status, locked)."
        ),
        parameters=MONTHLY_REPORT_QUERY_PARAMS,
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="PDF file containing the monthly attendance grid.",
            )
        },
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="monthly-report",
        renderer_classes=[MonthlyAttendancePDFRenderer],
    )
    def monthly_report(self, request, company_id=None):
        start, end = parse_month(request.query_params.get("month"))

        status_param = request.query_params.get("status")
        status_filters = (
            [value.strip() for value in status_param.split(",") if value.strip()]
            if status_param
            else []
        )

        locked_filter = None
        if "locked" in request.query_params:
            locked_filter = parse_bool(request.query_params.get("locked"))

        queryset = self._filter_employees(self.get_queryset(), request, company_id)
        queryset = self._apply_sorting(queryset, request)
        employees = list(queryset)

        calendar_result = build_monthly_calendar(
            employees,
            (start, end),
            user=request.user,
            include_pairs=False,
            include_adjustments=False,
            include_anomalies=False,
            stats_only=False,
            status_filters=status_filters,
            locked_filter=locked_filter,
            serializer_context=self.get_serializer_context(),
        )
        report_data = calendar_result["report"]

        filters_summary = self._summarise_report_filters(
            request, company_id, status_filters, locked_filter
        )

        company = None
        if company_id:
            company = Company.objects.filter(pk=company_id).first()

        pdf_context = {
            "request": request,
            "company": company,
            "filters": filters_summary,
        }
        pdf = render_monthly_attendance_pdf(report_data, pdf_context)
        filename = f"monthly_attendance_{report_data['month']}.pdf"
        return Response(
            pdf,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @extend_schema(
        summary="Lock or unlock computed attendance days",
        request=LockDaysSerializer,
        responses={
            200: OpenApiResponse(
                description="Number of AttDay rows updated",
                response=inline_serializer(
                    name="AttendanceCalendarLockResponse",
                    fields={"updated": serializers.IntegerField()},
                ),
            )
        },
        examples=[
            OpenApiExample(
                "Lock May 2024",
                value={
                    "start": "2024-05-01",
                    "end": "2024-05-31",
                    "employee_ids": [42, 43],
                    "locked": True,
                },
                request_only=True,
            ),
            OpenApiExample(
                "Lock response",
                value={"updated": 62},
                response_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["post"], url_path="lock")
    def lock(self, request, company_id=None):
        params = LockDaysSerializer(data=request.data or {})
        params.is_valid(raise_exception=True)
        data = params.validated_data
        start, end = data["start"], data["end"]
        employee_ids = data.get("employee_ids", [])
        queryset = AttDay.objects.filter(date__range=(start, end))
        if company_id:
            queryset = queryset.filter(
                Q(employee__trade_license__company_id=company_id)
                | Q(employee__department__branch__company_id=company_id)
                | Q(employee__project__branch__company_id=company_id)
            )
        if employee_ids:
            queryset = queryset.filter(employee_id__in=employee_ids)
        queryset = scope_queryset(queryset, request.user)
        with transaction.atomic():
            updated = queryset.update(locked=data.get("locked", True))
        return Response({"updated": updated})

    @extend_schema(
        summary="Proxy to create a manual attendance adjustment",
        request=AttAdjustmentSerializer,
        responses={
            201: OpenApiResponse(
                description="Created adjustment",
                response=AttAdjustmentSerializer,
            )
        },
        examples=[
            OpenApiExample(
                "Create adjustment",
                value={
                    "employee": 42,
                    "date": "2024-05-01",
                    "delta_work_min": -15,
                    "override_status": None,
                    "reason": "Late arrival waiver",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Mark full attendance",
                value={
                    "employee": 42,
                    "date": "2024-05-01",
                    "mark_full_attendance": True,
                    "reason": "Auto-fill to full shift",
                },
                request_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["post"], url_path="adjustments")
    def adjustments(self, request, company_id=None):
        serializer = AttAdjustmentSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        employee = serializer.validated_data["employee"]
        scoped_employee = scope_queryset(Employee.objects.filter(pk=employee.pk), request.user)
        if company_id:
            scoped_employee = scoped_employee.filter(
                Q(trade_license__company_id=company_id)
                | Q(department__branch__company_id=company_id)
                | Q(project__branch__company_id=company_id)
            )
        if not scoped_employee.exists():
            raise serializers.ValidationError({"detail": "Employee outside allowed scope"})
        adjustment = serializer.save(created_by_id=request.user.id)
        output = AttAdjustmentSerializer(adjustment, context=self.get_serializer_context())
        return Response(output.data, status=status.HTTP_201_CREATED)


document_filters(AttendanceCalendarViewSet)


@extend_schema_view(
    list=extend_schema(description="List manual attendance adjustments."),
    retrieve=extend_schema(description="Retrieve a manual attendance adjustment."),
    create=extend_schema(
        description="Create a manual attendance adjustment.",
        examples=[
            OpenApiExample(
                "Request",
                value={
                    "employee": 1,
                    "date": "2024-01-05",
                    "mark_full_attendance": True,
                    "reason": "Grant full shift credit",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Response",
                value={
                    "id": 1,
                    "employee": 1,
                    "date": "2024-01-05",
                    "delta_ot_regular_min": -30,
                    "override_status": "present",
                    "reason": "Reduce overtime by 30 minutes",
                    "created_by_id": 99,
                    "created_at": "2024-01-06T09:00:00Z",
                },
                response_only=True,
            ),
        ],
    ),
)
@extend_schema(
    tags=["Attendance"],
    description="Review and manage manual attendance adjustments.",
)
class AttAdjustmentViewSet(viewsets.ModelViewSet):
    queryset = AttAdjustment.objects.all().select_related("employee")
    serializer_class = AttAdjustmentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["employee", "date"]

    def get_queryset(self):
        return scope_queryset(super().get_queryset(), self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by_id=self.request.user.id)


document_filters(AttAdjustmentViewSet)


