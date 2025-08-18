from django.db import models
from django.utils import timezone
from datetime import timezone as dt_timezone
from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.response import Response
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as filters
from drf_spectacular.utils import extend_schema, OpenApiExample
import hmac
import json
import hashlib

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
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")
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
        if not isinstance(request.data, list):
            return Response(
                {"detail": "Expected a list of events."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = 0
        duplicates = 0
        for item in request.data:
            ser = AttEventIngestSerializer(data=item)
            if not ser.is_valid():
                return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
            data = ser.validated_data

            try:
                device = Device.objects.get(pk=data["device_id"])
            except Device.DoesNotExist:
                return Response(
                    {"detail": f"Unknown device {data['device_id']}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                ensure_in_scope(device, request.user, "device")
            except Exception as exc:  # pragma: no cover - permission
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

            raw_payload = item.copy()
            sig = request.headers.get("X-Signature") or raw_payload.pop("payload_sig", None)
            if not sig:
                return Response(
                    {"detail": "Missing signature"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            canonical = json.dumps(
                raw_payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            expected = hmac.new(
                key=device.hmac_secret.encode("utf-8"),
                msg=canonical,
                digestmod=hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, sig):
                return Response(
                    {"detail": "Invalid signature"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            try:
                employee = Employee.objects.get(pk=data["employee_id"])
            except Employee.DoesNotExist:
                return Response(
                    {"detail": f"Unknown employee {data['employee_id']}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                ensure_in_scope(employee, request.user, "employee")
            except Exception as exc:  # pragma: no cover - permission
                return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

            emp_co_id = employee_company_id(employee)
            if emp_co_id is None or emp_co_id != device.company_id:
                return Response(
                    {"detail": "Device and employee belong to different companies."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            ts = data["ts"]
            if timezone.is_naive(ts):
                ts = timezone.make_aware(ts)
            ts_utc = ts.astimezone(dt_timezone.utc)

            obj, created_flag = AttEvent.objects.get_or_create(
                employee=employee,
                ts=ts_utc,
                device=device,
                defaults={
                    "company_id": device.company_id,
                    "direction": data["direction"],
                    "provider": data["provider"],
                    "face_conf": data.get("confidence"),
                    "liveness": data.get("liveness"),
                    "payload_sig": sig,
                    "meta": data.get("meta", {}),
                },
            )
            if created_flag:
                created += 1
            else:
                duplicates += 1

        status_code = status.HTTP_201_CREATED
        return Response({"created": created, "duplicates": duplicates}, status=status_code)


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
