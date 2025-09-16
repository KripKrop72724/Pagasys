from datetime import timedelta, date

from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
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
from pagasys.models import Employee
from django.http import HttpResponse

from .models import AttDay, AttPair, AttAdjustment
from .reports import (
    get_late_comers,
    group_late_comers,
    render_late_comers_pdf,
)
from .serializers import (
    AttDaySerializer,
    AttPairSerializer,
    ManualAttPairSerializer,
    RecomputeRangeSerializer,
    LockDaysSerializer,
    AttAdjustmentSerializer,
)
from .tasks import (
    recompute_range_task,
    pair_employee_day_task,
    compute_employee_day_task,
)

MAX_RANGE_DAYS = 31
MAX_EMPLOYEES = 50


class LateComersPDFRenderer(BaseRenderer):
    media_type = "application/pdf"
    format = "pdf"
    charset = None

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


@extend_schema_view(
    list=extend_schema(
        description="List computed attendance days.",
        examples=[
            OpenApiExample(
                "IN-AUTO-OUT request",
                value={"employee": 1, "date": "2024-01-01"},
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
    filterset_fields = ["employee", "date", "status", "is_holiday", "is_rest_day", "locked"]

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
        records, stats = group_late_comers(records)
        pdf = render_late_comers_pdf(records, stats, start, end, request)
        filename = f"late_comers_{start}_{end}.pdf"
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename={filename}"
        return response


@extend_schema_view(
    list=extend_schema(
        description="List paired IN/OUT sessions. An 'auto' punch opens a new"
        " session when none is active or closes the current session.",
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
    filterset_fields = ["employee", "date", "source"]

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
                    "delta_ot_regular_min": -30,
                    "override_status": "present",
                    "reason": "Reduce overtime by 30 minutes",
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


