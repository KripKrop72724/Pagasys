from django.db import models
from django.core.exceptions import ValidationError


class Company(models.Model):
    """A company entity"""

    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name


class Branch(models.Model):
    """Company branch"""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="branches")
    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name


class Designation(models.Model):
    """Job designation tied to a company"""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="designations")
    name = models.CharField(max_length=100)
    level = models.PositiveIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ("company", "name")

    def __str__(self) -> str:
        return self.name


class TradeLicense(models.Model):
    """Trade license for a branch"""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="licenses")
    license_no = models.CharField(max_length=100, unique=True)
    issued_date = models.DateField()
    expiry_date = models.DateField()
    max_visas = models.PositiveIntegerField()

    def clean(self):
        if self.expiry_date < self.issued_date:
            raise ValidationError("expiry_date must be after issued_date")

    def __str__(self) -> str:
        return self.license_no


class Department(models.Model):
    """Department within a branch"""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=255)

    def __str__(self) -> str:
        return self.name


class Project(models.Model):
    """Project under a branch"""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="projects")
    name = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class Employee(models.Model):
    """Employee belonging to a department or project"""

    trade_license = models.ForeignKey(
        TradeLicense, on_delete=models.PROTECT, related_name="employees"
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
    )
    designation = models.ForeignKey(
        Designation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
    )
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    hire_date = models.DateField()
    employment_type = models.CharField(
        max_length=20,
        choices=[("permanent", "Permanent"), ("temporary", "Temporary")],
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(department__isnull=False, project__isnull=True)
                    | models.Q(department__isnull=True, project__isnull=False)
                ),
                name="employee_one_of_dept_or_proj",
            ),
            models.CheckConstraint(
                check=~models.Q(trade_license=None),
                name="employee_must_have_license",
            ),
        ]

    def clean(self):
        if not (bool(self.department) ^ bool(self.project)):
            raise ValidationError(
                "Employee must belong to exactly one: department or project"
            )
        if self.trade_license.employees.count() >= self.trade_license.max_visas:
            raise ValidationError("Visa quota for this license has been reached")
        if self.designation and self.designation.company != self.trade_license.branch.company:
            raise ValidationError("Designation must belong to the same company")

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"
