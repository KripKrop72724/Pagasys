"""Core HR models used throughout the application."""

from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import AbstractUser


class Company(models.Model):
    """Registered company."""

    name = models.CharField(
        max_length=255,
        help_text="Official company name",
    )

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["name"], name="company_name_idx")
        ]

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
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "name"], name="branch_company_name_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name}"


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
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "name", "level"], name="designation_comp_name_lvl_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.company.name}"


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
        ordering = ["id"]
        indexes = [
            models.Index(fields=["company", "license_no"], name="license_company_no_idx"),
            models.Index(fields=["company", "issued_date", "expiry_date"], name="license_date_range_idx"),
        ]

    def clean(self):
        """Validate logical consistency and branch-company rules."""
        if self.expiry_date < self.issued_date:
            raise ValidationError("Expiry date must be after issued date")

        branches = getattr(self, "_branches_for_validation", None)
        if branches is None:
            branches = self.branches.all()
        invalid = [b for b in branches if b.company_id != self.company_id]
        if invalid:
            raise ValidationError("Branches must belong to the license company")

    def __str__(self) -> str:
        branches = ", ".join(b.name for b in self.branches.all())
        return f"{self.license_no} - {self.company.name}" + (f" - {branches}" if branches else "")


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
        ordering = ["id"]
        indexes = [
            models.Index(fields=["branch", "name"], name="dept_branch_name_idx")
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.branch.name} - {self.branch.company.name}"


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
        ordering = ["id"]
        indexes = [
            models.Index(fields=["branch", "name"], name="project_branch_name_idx"),
            models.Index(fields=["branch", "start_date", "end_date"], name="project_date_range_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.name} - {self.branch.name} - {self.branch.company.name}"



class Employee(AbstractUser):
    """User account combined with employment info."""

    VISA_TYPE_CHOICES = [
        ("company", "Company"),
        ("personal", "Personal"),
    ]

    visa_type = models.CharField(
        max_length=20,
        choices=VISA_TYPE_CHOICES,
        default="company",
        help_text="Whether the employee uses a company or personal visa",
    )

    trade_license = models.ForeignKey(
        TradeLicense,
        null=True,
        blank=True,
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
    hire_date = models.DateField(help_text="Date hired")
    employment_type = models.CharField(
        max_length=20,
        choices=[("permanent", "Permanent"), ("temporary", "Temporary")],
        help_text="Employment contract type",
    )

    @property
    def company(self):
        """Convenience access to the employee's company."""
        if self.trade_license:
            return self.trade_license.company
        if self.department:
            return self.department.branch.company
        if self.project:
            return self.project.branch.company
        return None

    @property
    def branch(self):
        """Branch derived from department or project."""
        if self.department:
            return self.department.branch
        if self.project:
            return self.project.branch
        return None

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(department__isnull=False, project__isnull=True)
                    | models.Q(department__isnull=True, project__isnull=False)
                ),
                name="employee_one_of_dept_or_proj",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(visa_type="company", trade_license__isnull=False)
                    | models.Q(visa_type="personal", trade_license__isnull=True)
                ),
                name="employee_license_matches_visa_type",
            ),
        ]
        verbose_name_plural = "employees"
        ordering = ["id"]
        indexes = [
            models.Index(
                fields=["trade_license", "department", "employment_type"],
                name="emp_lic_dept_type_idx",
            ),
            models.Index(
                fields=["trade_license", "project", "employment_type"],
                name="emp_lic_proj_type_idx",
            ),
            models.Index(
                fields=["department", "designation", "employment_type"],
                name="emp_dept_desig_type_idx",
            ),
            models.Index(
                fields=["project", "designation", "employment_type"],
                name="emp_proj_desig_type_idx",
            ),
            models.Index(fields=["first_name", "last_name"], name="emp_name_idx"),
        ]

    def clean(self):
        super().clean()
        if not (bool(self.department) ^ bool(self.project)):
            raise ValidationError(
                "Employee must belong to exactly one of department or project"
            )

        branch = self.department.branch if self.department else self.project.branch

        if self.visa_type == "company":
            if not self.trade_license:
                raise ValidationError({"trade_license": ["This field is required for company visas"]})

            current = self.trade_license.employees.exclude(pk=self.pk).count()
            if current >= self.trade_license.max_visas:
                raise ValidationError("Visa quota reached")

            if self.designation and self.designation.company != self.trade_license.company:
                raise ValidationError("Designation must match company")

            if self.trade_license.company != branch.company:
                raise ValidationError("License company must match branch company")

        else:  # personal visa
            if self.trade_license:
                raise ValidationError({"trade_license": ["Trade license must be empty for personal visa"]})

        # When personal visa but designation set with company mismatch? We still ensure designation matches branch.company
        if self.designation and self.designation.company != branch.company:
            raise ValidationError("Designation must match company")

    def __str__(self) -> str:
        parts = [f"{self.first_name} {self.last_name}"]
        if self.trade_license:
            parts.append(self.trade_license.company.name)
        elif self.branch:
            parts.append(self.branch.company.name)
        if self.department:
            parts.append(self.department.branch.name)
            parts.append(self.department.name)
        elif self.project:
            parts.append(self.project.branch.name)
            parts.append(self.project.name)
        if self.trade_license:
            parts.append(self.trade_license.license_no)
        if self.designation:
            parts.append(self.designation.name)
        return " - ".join(parts)

    def save(self, *args, **kwargs):
        """Ensure visa quota checks are performed atomically."""
        from django.db import transaction

        if self.visa_type == "company" and self.trade_license_id:
            with transaction.atomic():
                lic = (
                    TradeLicense.objects.select_for_update()
                    .get(pk=self.trade_license_id)
                )
                current = lic.employees.exclude(pk=self.pk).count()
                if current >= lic.max_visas:
                    raise ValidationError("Visa quota reached")
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)
