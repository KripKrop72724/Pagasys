"""Core HR models used throughout the application."""

from django.db import models
from django.core.exceptions import ValidationError


class Company(models.Model):
    """Registered company."""

    name = models.CharField(
        max_length=255,
        help_text="Official company name",
    )

    class Meta:
        verbose_name_plural = "companies"

    def __str__(self) -> str:
        return self.name


class Branch(models.Model):
    """Individual branch office of a company."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="branches",
        help_text="Parent company",
    )
    name = models.CharField(
        max_length=255,
        help_text="Branch office name",
    )

    class Meta:
        verbose_name_plural = "branches"

    def __str__(self) -> str:
        return self.name


class Designation(models.Model):
    """Job title defined per company."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="designations",
        help_text="Company that defines the designation",
    )
    name = models.CharField(
        max_length=100,
        help_text="Job title name",
    )
    level = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Seniority level",
    )
    description = models.TextField(
        blank=True,
        help_text="Optional description of this designation",
    )

    class Meta:
        unique_together = (("company", "name"),)
        verbose_name_plural = "designations"

    def __str__(self) -> str:
        return self.name


class TradeLicense(models.Model):
    """Government trade license issued to a company covering branches."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="licenses",
        help_text="License owning company",
    )
    branches = models.ManyToManyField(
        Branch,
        related_name="licenses",
        help_text="Which branches this license covers",
    )
    license_no = models.CharField(
        max_length=100,
        unique=True,
        help_text="Official license number",
    )
    issued_date = models.DateField(help_text="Date license was issued")
    expiry_date = models.DateField(help_text="Date license expires")
    max_visas = models.PositiveIntegerField(help_text="Maximum number of visa slots")

    class Meta:
        verbose_name = "trade license"
        verbose_name_plural = "trade licenses"

    def clean(self):
        """Validate logical consistency of license dates."""
        if self.expiry_date < self.issued_date:
            raise ValidationError("Expiry date must be after issued date")

    def __str__(self) -> str:
        return self.license_no


class Department(models.Model):
    """Organizational department within a branch."""

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="departments",
        help_text="Branch that houses the department",
    )
    name = models.CharField(
        max_length=255,
        help_text="Department name",
    )

    class Meta:
        verbose_name_plural = "departments"

    def __str__(self) -> str:
        return self.name


class Project(models.Model):
    """Project carried out by a branch."""

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="projects",
        help_text="Branch executing the project",
    )
    name = models.CharField(
        max_length=255,
        help_text="Project name",
    )
    start_date = models.DateField(help_text="Project start date")
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Project end date",
    )

    class Meta:
        verbose_name_plural = "projects"

    def __str__(self) -> str:
        return self.name


class Employee(models.Model):
    """Employee belonging to a department or a project."""

    trade_license = models.ForeignKey(
        TradeLicense,
        on_delete=models.PROTECT,
        related_name="employees",
        help_text="Visa license assigned",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Department assigned",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Project assigned",
    )
    designation = models.ForeignKey(
        Designation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employees",
        help_text="Job designation",
    )
    first_name = models.CharField(max_length=255, help_text="Given name")
    last_name = models.CharField(max_length=255, help_text="Family name")
    hire_date = models.DateField(help_text="Date hired")
    employment_type = models.CharField(
        max_length=20,
        choices=[("permanent", "Permanent"), ("temporary", "Temporary")],
        help_text="Employment contract type",
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
        verbose_name_plural = "employees"

    def clean(self):
        if not (bool(self.department) ^ bool(self.project)):
            raise ValidationError(
                "Employee must belong to exactly one of department or project"
            )
        if self.trade_license.employees.count() >= self.trade_license.max_visas:
            raise ValidationError("Visa quota reached")
        if self.designation and self.designation.company != self.trade_license.company:
            raise ValidationError("Designation must match company")

        # ensure employee's branch is covered by their license
        if self.department:
            emp_branch = self.department.branch
        else:
            emp_branch = self.project.branch

        if emp_branch not in self.trade_license.branches.all():
            raise ValidationError(
                f"Branch {emp_branch.name!r} is not covered by license {self.trade_license.license_no!r}"
            )

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"
