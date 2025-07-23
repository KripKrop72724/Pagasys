from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view

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
    bulk_create_response_serializer,
    bulk_update_response_serializer,
    bulk_delete_response_serializer,
)


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
                    created_objs.append(ser.save())
                except Exception as exc:
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
        seen_ids = set()
        for item in request.data:
            obj_id = item.get("id")
            if obj_id is None:
                errors.append({"data": item, "errors": {"id": ["This field is required."]}})
                continue
            if obj_id in seen_ids:
                errors.append({"data": item, "errors": {"id": ["Duplicate id."]}})
                continue
            seen_ids.add(obj_id)
            try:
                instance = self.get_queryset().get(id=obj_id)
            except self.get_queryset().model.DoesNotExist:
                errors.append({"data": item, "errors": {"id": ["Not found."]}})
                continue

            ser = self.get_serializer(instance, data=item, partial=True)
            if ser.is_valid():
                try:
                    updated_objs.append(ser.save())
                except Exception as exc:
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
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsCompanyAdmin]
    filterset_fields = ["name"]
    ordering_fields = ["name"]


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
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsBranchManager]
    filterset_fields = ["company", "name"]
    ordering_fields = ["name"]


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
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsCompanyAdmin]
    filterset_fields = ["company", "name", "level"]
    ordering_fields = ["name", "level"]


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
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsBranchManager]
    filterset_fields = ["company", "branches", "license_no", "issued_date", "expiry_date"]
    ordering_fields = ["license_no", "issued_date", "expiry_date"]


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
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsDepartmentManager]
    filterset_fields = ["branch", "name"]
    ordering_fields = ["name"]


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
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsProjectManager]
    filterset_fields = ["branch", "name", "start_date", "end_date"]
    ordering_fields = ["name", "start_date", "end_date"]


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

