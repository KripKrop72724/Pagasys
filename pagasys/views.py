from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view
from drf_spectacular.types import OpenApiTypes

from .permissions import (
    IsBranchManager,
    IsCompanyAdmin,
    IsPayrollManager,
    IsDepartmentManager,
    IsProjectManager,
)

from .models import (
    Company,
    Branch,
    Designation,
    TradeLicense,
    Department,
    Project,
    Employee,
)
from .serializers import (
    CompanySerializer,
    BranchSerializer,
    DesignationSerializer,
    TradeLicenseSerializer,
    DepartmentSerializer,
    ProjectSerializer,
    EmployeeSerializer,
    IdListSerializer,
)


class BulkCreateMixin:
    """Mixin providing a robust bulk create action."""

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk_create(self, request, *args, **kwargs):
        """Create many objects in a single request."""
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        self.perform_bulk_create(serializer)
        headers = self.get_success_headers(serializer.data if serializer.data else None)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_bulk_create(self, serializer):
        serializer.save()


class BulkUpdateMixin:
    """Mixin providing a robust bulk update action."""

    @action(detail=False, methods=["patch"], url_path="bulk-update")
    def bulk_update(self, request, *args, **kwargs):
        """Update many objects in a single request."""
        if not isinstance(request.data, list):
            return Response({"detail": "Expected a list of objects."}, status=status.HTTP_400_BAD_REQUEST)

        ids = [item.get("id") for item in request.data]
        if None in ids:
            return Response({"detail": "Each object must include 'id'."}, status=status.HTTP_400_BAD_REQUEST)

        instances = {obj.id: obj for obj in self.get_queryset().filter(id__in=ids)}
        if len(instances) != len(ids):
            return Response({"detail": "Some objects not found."}, status=status.HTTP_404_NOT_FOUND)

        updated = []
        for item in request.data:
            instance = instances[item["id"]]
            ser = self.get_serializer(instance, data=item, partial=True)
            ser.is_valid(raise_exception=True)
            updated.append(ser.save())

        out_ser = self.get_serializer(updated, many=True)
        return Response(out_ser.data, status=status.HTTP_200_OK)


class BulkDeleteMixin:
    """Mixin providing a robust bulk delete action."""

    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request, *args, **kwargs):
        """Delete many objects in a single request."""
        if not isinstance(request.data, list):
            return Response({"detail": "Expected a list of IDs."}, status=status.HTTP_400_BAD_REQUEST)

        ids = [id_ for id_ in request.data if id_ is not None]
        deleted, _ = self.get_queryset().filter(id__in=ids).delete()
        return Response({"deleted": deleted}, status=status.HTTP_200_OK)


@extend_schema_view(
    bulk_create=extend_schema(
        request=CompanySerializer(many=True),
        responses=CompanySerializer(many=True),
        description="Create multiple companies in one request",
    ),
    bulk_update=extend_schema(
        request=CompanySerializer(many=True),
        responses=CompanySerializer(many=True),
        description="Update multiple companies in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple companies by ID",
    ),
)
class CompanyViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for companies"""

    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsCompanyAdmin]
    filterset_fields = ["name"]
    ordering_fields = ["name"]


@extend_schema_view(
    bulk_create=extend_schema(
        request=BranchSerializer(many=True),
        responses=BranchSerializer(many=True),
        description="Create multiple branches in one request",
    ),
    bulk_update=extend_schema(
        request=BranchSerializer(many=True),
        responses=BranchSerializer(many=True),
        description="Update multiple branches in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple branches by ID",
    ),
)
class BranchViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for branches"""

    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsBranchManager]
    filterset_fields = ["company", "name"]
    ordering_fields = ["name"]


@extend_schema_view(
    bulk_create=extend_schema(
        request=DesignationSerializer(many=True),
        responses=DesignationSerializer(many=True),
        description="Create multiple designations in one request",
    ),
    bulk_update=extend_schema(
        request=DesignationSerializer(many=True),
        responses=DesignationSerializer(many=True),
        description="Update multiple designations in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple designations by ID",
    ),
)
class DesignationViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for designations"""

    queryset = Designation.objects.all()
    serializer_class = DesignationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsCompanyAdmin]
    filterset_fields = ["company", "name", "level"]
    ordering_fields = ["name", "level"]


@extend_schema_view(
    bulk_create=extend_schema(
        request=TradeLicenseSerializer(many=True),
        responses=TradeLicenseSerializer(many=True),
        description="Create multiple trade licenses in one request",
    ),
    bulk_update=extend_schema(
        request=TradeLicenseSerializer(many=True),
        responses=TradeLicenseSerializer(many=True),
        description="Update multiple trade licenses in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple trade licenses by ID",
    ),
)
class TradeLicenseViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for trade licenses"""

    queryset = TradeLicense.objects.all()
    serializer_class = TradeLicenseSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsBranchManager]
    filterset_fields = ["company", "branches", "license_no", "issued_date", "expiry_date"]
    ordering_fields = ["license_no", "issued_date", "expiry_date"]


@extend_schema_view(
    bulk_create=extend_schema(
        request=DepartmentSerializer(many=True),
        responses=DepartmentSerializer(many=True),
        description="Create multiple departments in one request",
    ),
    bulk_update=extend_schema(
        request=DepartmentSerializer(many=True),
        responses=DepartmentSerializer(many=True),
        description="Update multiple departments in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple departments by ID",
    ),
)
class DepartmentViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for departments"""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsDepartmentManager]
    filterset_fields = ["branch", "name"]
    ordering_fields = ["name"]


@extend_schema_view(
    bulk_create=extend_schema(
        request=ProjectSerializer(many=True),
        responses=ProjectSerializer(many=True),
        description="Create multiple projects in one request",
    ),
    bulk_update=extend_schema(
        request=ProjectSerializer(many=True),
        responses=ProjectSerializer(many=True),
        description="Update multiple projects in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple projects by ID",
    ),
)
class ProjectViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for projects"""

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsProjectManager]
    filterset_fields = ["branch", "name", "start_date", "end_date"]
    ordering_fields = ["name", "start_date", "end_date"]


@extend_schema_view(
    bulk_create=extend_schema(
        request=EmployeeSerializer(many=True),
        responses=EmployeeSerializer(many=True),
        description="Create multiple employees in one request",
    ),
    bulk_update=extend_schema(
        request=EmployeeSerializer(many=True),
        responses=EmployeeSerializer(many=True),
        description="Update multiple employees in one request",
    ),
    bulk_delete=extend_schema(
        request=IdListSerializer,
        responses=OpenApiTypes.OBJECT,
        description="Delete multiple employees by ID",
    ),
)
class EmployeeViewSet(BulkCreateMixin, BulkUpdateMixin, BulkDeleteMixin, viewsets.ModelViewSet):
    """CRUD for employees"""

    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsPayrollManager]
    filterset_fields = [
        "trade_license",
        "department",
        "project",
        "designation",
        "first_name",
        "last_name",
    ]
    ordering_fields = ["first_name", "last_name", "hire_date"]

