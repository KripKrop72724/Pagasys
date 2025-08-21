from rest_framework import generics, status, viewsets
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import OrderingFilter
from django.http import HttpResponse
from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
)
from django_filters.rest_framework import DjangoFilterBackend
from django_filters import rest_framework as filters

from django.db import IntegrityError, models, transaction

from .permissions import CustomObjectPermission, GroupRequiredPermission
from .utils import scope_queryset

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
    WorkCalendar,
    Holiday,
    ShiftTemplate,
    ShiftRule,
    RosterEntry,
    LeaveType,
)
from .serializers import (
    CompanySerializer,
    BranchSerializer,
    DesignationSerializer,
    TradeLicenseSerializer,
    DepartmentSerializer,
    ProjectSerializer,
    EmployeeSerializer,
    WorkCalendarSerializer,
    HolidaySerializer,
    ShiftTemplateSerializer,
    ShiftRuleSerializer,
    RosterEntrySerializer,
    LeaveTypeSerializer,
    IdListSerializer,
    bulk_create_response_serializer,
    bulk_update_response_serializer,
    bulk_delete_response_serializer,
)
from .openapi_utils import document_filters


@extend_schema_view(
    get=extend_schema(
        description="Retrieve the profile for the currently authenticated user.",
        responses=EmployeeSerializer,
    )
)
class ProfileView(generics.RetrieveAPIView):
    """Expose the authenticated user's profile.

    Returns the same representation as :class:`EmployeeSerializer` while
    ensuring users can only access their own data.
    """

    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class BulkCreateMixin:
    """Mixin providing a robust bulk create action."""

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request, *args, **kwargs):
        """Create many objects, skipping invalid ones."""
        if not isinstance(request.data, list):
            return Response({"detail": "Expected a list of objects."}, status=status.HTTP_400_BAD_REQUEST)

        created_objs = []
        errors = []
        for item in request.data:
            ser = self.get_serializer(data=item)
            if ser.is_valid():
                try:
                    with transaction.atomic():
                        created_objs.append(ser.save())
                except IntegrityError as exc:
                    errors.append({"data": item, "errors": {"non_field_errors": [str(exc)]}})
            else:
                errors.append({"data": item, "errors": ser.errors})

        out_ser = self.get_serializer(created_objs, many=True)
        status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_201_CREATED
        return Response({"created": out_ser.data, "errors": errors}, status=status_code)


class BulkUpdateMixin:
    """Mixin providing a robust bulk update action."""

    @action(detail=False, methods=["patch"], url_path="bulk-update")
    def bulk_update(self, request, *args, **kwargs):
        """Update many objects in a single request."""
        if not isinstance(request.data, list):
            return Response({"detail": "Expected a list of objects."}, status=status.HTTP_400_BAD_REQUEST)

        updated_objs = []
        errors = []
        seen = set()
        for item in request.data:
            obj_id = item.get("id")
            if obj_id is None:
                errors.append({"data": item, "errors": {"id": ["This field is required."]}})
                continue
            if obj_id in seen:
                errors.append({"data": item, "errors": {"id": ["Duplicate id."]}})
                continue
            seen.add(obj_id)
            try:
                instance = self.get_queryset().get(id=obj_id)
            except self.get_queryset().model.DoesNotExist:
                errors.append({"data": item, "errors": {"id": ["Not found."]}})
                continue

            ser = self.get_serializer(instance, data=item, partial=True)
            if ser.is_valid():
                try:
                    with transaction.atomic():
                        updated_objs.append(ser.save())
                except IntegrityError as exc:
                    errors.append({"data": item, "errors": {"non_field_errors": [str(exc)]}})
            else:
                errors.append({"data": item, "errors": ser.errors})

        out_ser = self.get_serializer(updated_objs, many=True)
        status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response({"updated": out_ser.data, "errors": errors}, status=status_code)


class BulkDeleteMixin:
    """Mixin providing a robust bulk delete action."""

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request, *args, **kwargs):
        """Delete many objects in a single request."""
        if not isinstance(request.data, list):
            return Response({"detail": "Expected a list of IDs."}, status=status.HTTP_400_BAD_REQUEST)

        ids = []
        errors = []
        for raw in request.data:
            if raw is None:
                continue
            try:
                int_id = int(raw)
            except (TypeError, ValueError):
                errors.append({"id": raw, "errors": ["Invalid id."]})
                continue
            ids.append(int_id)

        queryset = self.get_queryset().filter(id__in=ids)
        found_ids = list(queryset.values_list("id", flat=True))
        deleted, _ = queryset.delete()
        missing = [i for i in ids if i not in found_ids]
        errors += [{"id": i, "errors": ["Not found."]} for i in missing]
        status_code = status.HTTP_207_MULTI_STATUS if errors else status.HTTP_200_OK
        return Response({"deleted": deleted, "errors": errors}, status=status_code)


class EmployeeFilter(filters.FilterSet):
    """Filters exposing every Employee field plus branch and groups."""

    branch = filters.NumberFilter(method="filter_branch")
    groups = filters.NumberFilter(field_name="groups")

    class Meta:
        model = Employee
        fields = [
            f.name
            for f in Employee._meta.get_fields()
            if (getattr(f, "concrete", False) or f.many_to_many)
            and not f.auto_created
            and f.name != "password"
        ] + ["branch", "groups"]

    def filter_branch(self, queryset, name, value):
        return queryset.filter(
            models.Q(department__branch_id=value) | models.Q(project__branch_id=value)
        )


@extend_schema_view(
    bulk_create=extend_schema(
        request=CompanySerializer(many=True),
        responses=bulk_create_response_serializer(CompanySerializer),
        description="Create multiple companies in one request",
    ),
    bulk_update=extend_schema(
        request=CompanySerializer(many=True),
        responses=bulk_update_response_serializer(CompanySerializer),
        description="Update multiple companies in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple companies by ID",
    ),
)
class CompanyViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for companies"""

    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = []
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)




@extend_schema_view(
    bulk_create=extend_schema(
        request=BranchSerializer(many=True),
        responses=bulk_create_response_serializer(BranchSerializer),
        description="Create multiple branches in one request",
    ),
    bulk_update=extend_schema(
        request=BranchSerializer(many=True),
        responses=bulk_update_response_serializer(BranchSerializer),
        description="Update multiple branches in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple branches by ID",
    ),
)
class BranchViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for branches"""

    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=DesignationSerializer(many=True),
        responses=bulk_create_response_serializer(DesignationSerializer),
        description="Create multiple designations in one request",
    ),
    bulk_update=extend_schema(
        request=DesignationSerializer(many=True),
        responses=bulk_update_response_serializer(DesignationSerializer),
        description="Update multiple designations in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple designations by ID",
    ),
)
class DesignationViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for designations"""

    queryset = Designation.objects.all()
    serializer_class = DesignationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name", "level"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=TradeLicenseSerializer(many=True),
        responses=bulk_create_response_serializer(TradeLicenseSerializer),
        description="Create multiple trade licenses in one request",
    ),
    bulk_update=extend_schema(
        request=TradeLicenseSerializer(many=True),
        responses=bulk_update_response_serializer(TradeLicenseSerializer),
        description="Update multiple trade licenses in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple trade licenses by ID",
    ),
)
class TradeLicenseViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for trade licenses"""

    queryset = TradeLicense.objects.all()
    serializer_class = TradeLicenseSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["license_no", "issued_date", "expiry_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=DepartmentSerializer(many=True),
        responses=bulk_create_response_serializer(DepartmentSerializer),
        description="Create multiple departments in one request",
    ),
    bulk_update=extend_schema(
        request=DepartmentSerializer(many=True),
        responses=bulk_update_response_serializer(DepartmentSerializer),
        description="Update multiple departments in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple departments by ID",
    ),
)
class DepartmentViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for departments"""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Branch Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=ProjectSerializer(many=True),
        responses=bulk_create_response_serializer(ProjectSerializer),
        description="Create multiple projects in one request",
    ),
    bulk_update=extend_schema(
        request=ProjectSerializer(many=True),
        responses=bulk_update_response_serializer(ProjectSerializer),
        description="Update multiple projects in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple projects by ID",
    ),
)
class ProjectViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for projects"""

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Branch Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name", "start_date", "end_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=EmployeeSerializer(many=True),
        responses=bulk_create_response_serializer(EmployeeSerializer),
        description="Create multiple employees in one request",
    ),
    bulk_update=extend_schema(
        request=EmployeeSerializer(many=True),
        responses=bulk_update_response_serializer(EmployeeSerializer),
        description="Update multiple employees in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple employees by ID",
    ),
)
class EmployeeViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for employees"""

    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = [
        "Company Admin",
        "Branch Manager",
        "Payroll Manager",
        "Department Manager",
        "Project Manager",
        "Employee",
    ]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = EmployeeFilter
    ordering_fields = ["first_name", "last_name", "hire_date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


document_filters(CompanyViewSet)
document_filters(BranchViewSet)
document_filters(DesignationViewSet)
document_filters(TradeLicenseViewSet)
document_filters(DepartmentViewSet)
document_filters(ProjectViewSet)
document_filters(EmployeeViewSet)


@extend_schema_view(
    bulk_create=extend_schema(
        request=WorkCalendarSerializer(many=True),
        responses=bulk_create_response_serializer(WorkCalendarSerializer),
        description="Create multiple work calendars",
    ),
    bulk_update=extend_schema(
        request=WorkCalendarSerializer(many=True),
        responses=bulk_update_response_serializer(WorkCalendarSerializer),
        description="Update multiple work calendars",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple work calendars by ID",
    ),
)
class WorkCalendarViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for work calendars"""

    queryset = WorkCalendar.objects.all()
    serializer_class = WorkCalendarSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Payroll Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=HolidaySerializer(many=True),
        responses=bulk_create_response_serializer(HolidaySerializer),
        description="Create multiple holidays",
    ),
    bulk_update=extend_schema(
        request=HolidaySerializer(many=True),
        responses=bulk_update_response_serializer(HolidaySerializer),
        description="Update multiple holidays",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple holidays by ID",
    ),
)
class HolidayViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for holidays"""

    queryset = Holiday.objects.all()
    serializer_class = HolidaySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Payroll Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["date", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=ShiftTemplateSerializer(many=True),
        responses=bulk_create_response_serializer(ShiftTemplateSerializer),
        description="Create multiple shift templates",
    ),
    bulk_update=extend_schema(
        request=ShiftTemplateSerializer(many=True),
        responses=bulk_update_response_serializer(ShiftTemplateSerializer),
        description="Update multiple shift templates",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple shift templates by ID",
    ),
)
class ShiftTemplateViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for shift templates"""

    queryset = ShiftTemplate.objects.all()
    serializer_class = ShiftTemplateSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Payroll Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=ShiftRuleSerializer(many=True),
        responses=bulk_create_response_serializer(ShiftRuleSerializer),
        description="Create multiple shift rules",
    ),
    bulk_update=extend_schema(
        request=ShiftRuleSerializer(many=True),
        responses=bulk_update_response_serializer(ShiftRuleSerializer),
        description="Update multiple shift rules",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple shift rules by ID",
    ),
)
class ShiftRuleViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for shift rules"""

    queryset = ShiftRule.objects.all()
    serializer_class = ShiftRuleSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Payroll Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = [
        "shift",
        "kind",
        "value",
        "active_from",
        "active_to",
        "weekdays",
    ]
    ordering_fields = ["kind"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=RosterEntrySerializer(many=True),
        responses=bulk_create_response_serializer(RosterEntrySerializer),
        description="Create multiple roster entries",
    ),
    bulk_update=extend_schema(
        request=RosterEntrySerializer(many=True),
        responses=bulk_update_response_serializer(RosterEntrySerializer),
        description="Update multiple roster entries",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple roster entries by ID",
    ),
)
class RosterEntryViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for roster entries"""

    queryset = RosterEntry.objects.all()
    serializer_class = RosterEntrySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Payroll Manager", "Branch Manager", "Department Manager", "Project Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = "__all__"
    ordering_fields = ["date"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


@extend_schema_view(
    bulk_create=extend_schema(
        request=LeaveTypeSerializer(many=True),
        responses=bulk_create_response_serializer(LeaveTypeSerializer),
        description="Create multiple leave types",
    ),
    bulk_update=extend_schema(
        request=LeaveTypeSerializer(many=True),
        responses=bulk_update_response_serializer(LeaveTypeSerializer),
        description="Update multiple leave types",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=bulk_delete_response_serializer(),
        description="Delete multiple leave types by ID",
    ),
)
class LeaveTypeViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for leave types"""

    queryset = LeaveType.objects.all()
    serializer_class = LeaveTypeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, GroupRequiredPermission, CustomObjectPermission]
    required_groups = ["Company Admin", "Payroll Manager"]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = [
        "company",
        "code",
        "name",
        "paid_pct",
        "requires_doc",
        "max_days_per_year",
    ]
    ordering_fields = ["code", "name"]

    def get_queryset(self):
        qs = super().get_queryset()
        return scope_queryset(qs, self.request.user)


document_filters(WorkCalendarViewSet)
document_filters(HolidayViewSet)
document_filters(ShiftTemplateViewSet)
document_filters(ShiftRuleViewSet)
document_filters(RosterEntryViewSet)
document_filters(LeaveTypeViewSet)


def healthz(request):
    """Simple health check returning HTTP 200."""
    return HttpResponse("ok")
