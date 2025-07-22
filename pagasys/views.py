from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions

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
)


class CompanyViewSet(viewsets.ModelViewSet):
    """CRUD for companies"""

    queryset = Company.objects.all()
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsCompanyAdmin]
    filterset_fields = ["name"]
    ordering_fields = ["name"]


class BranchViewSet(viewsets.ModelViewSet):
    """CRUD for branches"""

    queryset = Branch.objects.all()
    serializer_class = BranchSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsBranchManager]
    filterset_fields = ["company", "name"]
    ordering_fields = ["name"]


class DesignationViewSet(viewsets.ModelViewSet):
    """CRUD for designations"""

    queryset = Designation.objects.all()
    serializer_class = DesignationSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsCompanyAdmin]
    filterset_fields = ["company", "name", "level"]
    ordering_fields = ["name", "level"]


class TradeLicenseViewSet(viewsets.ModelViewSet):
    """CRUD for trade licenses"""

    queryset = TradeLicense.objects.all()
    serializer_class = TradeLicenseSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsBranchManager]
    filterset_fields = ["branch", "license_no", "issued_date", "expiry_date"]
    ordering_fields = ["license_no", "issued_date", "expiry_date"]


class DepartmentViewSet(viewsets.ModelViewSet):
    """CRUD for departments"""

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsDepartmentManager]
    filterset_fields = ["branch", "name"]
    ordering_fields = ["name"]


class ProjectViewSet(viewsets.ModelViewSet):
    """CRUD for projects"""

    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, DjangoModelPermissions, IsProjectManager]
    filterset_fields = ["branch", "name", "start_date", "end_date"]
    ordering_fields = ["name", "start_date", "end_date"]


class EmployeeViewSet(viewsets.ModelViewSet):
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

