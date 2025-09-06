from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)

from pagasys.openapi_utils import document_filters
from pagasys.utils import scope_queryset

from .models import AttDay, AttPair, AttAdjustment
from .serializers import (
    AttDaySerializer,
    AttPairSerializer,
    ManualAttPairSerializer,
    RecomputeRangeSerializer,
    LockDaysSerializer,
    AttAdjustmentSerializer,
)
from .tasks import recompute_range_task


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


