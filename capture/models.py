from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from pagasys.models import Company, Branch, Department, Project, Employee


class AttendanceDevice(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="devices")
    name = models.CharField(max_length=120)
    api_key = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)

    branch = models.ForeignKey(Branch, null=True, blank=True, on_delete=models.SET_NULL, related_name="devices")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.SET_NULL, related_name="devices")
    project = models.ForeignKey(Project, null=True, blank=True, on_delete=models.SET_NULL, related_name="devices")

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_m = models.PositiveIntegerField(null=True, blank=True)

    last_seen = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "branch", "department", "project"]),
            models.Index(fields=["api_key"]),
        ]

    def clean(self):
        targets = [self.branch, self.department, self.project]
        if sum(bool(x) for x in targets) > 1:
            raise ValidationError("Attach device to at most one of branch/department/project")
        if any([self.latitude, self.longitude, self.radius_m]) and not all(
            [self.latitude, self.longitude, self.radius_m]
        ):
            raise ValidationError("Geofence requires latitude, longitude and radius_m")

    def __str__(self):
        scope = self.branch or self.department or self.project
        return f"{self.name} [{self.company}] ({scope or 'company-wide'})"


class FaceEnrollment(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="face_enrollment")
    collection_id = models.CharField(max_length=128)
    face_ids = models.JSONField(default=list)
    STATUS_CHOICES = [("active", "active"), ("revoked", "revoked"), ("pending", "pending")]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee_id}:{self.status} ({len(self.face_ids)} faces)"


class EnrollmentLink(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="enrollment_links")
    token = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveSmallIntegerField(default=1)
    uses = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["token", "expires_at"])]

    @property
    def is_valid(self):
        now = timezone.now()
        return (self.used_at is None) and (self.expires_at >= now) and (self.uses < self.max_uses)

    def mark_used(self):
        self.uses += 1
        self.used_at = timezone.now()
        self.save(update_fields=["uses", "used_at"])


class PunchEvent(models.Model):
    device = models.ForeignKey(AttendanceDevice, on_delete=models.PROTECT, related_name="events")
    company = models.ForeignKey(Company, on_delete=models.PROTECT)
    employee = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL)
    matched_employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="matched_events",
    )
    action = models.CharField(max_length=8, choices=[("in", "in"), ("out", "out"), ("auto", "auto")], default="auto")

    device_ts = models.DateTimeField()
    server_ts = models.DateTimeField(auto_now_add=True)

    s3_key = models.CharField(max_length=300, blank=True)
    image_bytes_sha256 = models.CharField(max_length=64, blank=True)

    face_matched = models.BooleanField(default=False)
    face_confidence = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)

    roster_date = models.DateField(null=True, blank=True)
    requires_face = models.BooleanField(default=False)
    out_of_scope = models.BooleanField(default=False)
    geofence_ok = models.BooleanField(default=True)
    notes = models.CharField(max_length=255, blank=True)

    external_id = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["company", "employee", "device_ts"]),
            models.Index(fields=["device", "external_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["device", "external_id"],
                name="uniq_device_external_id_nonempty",
                condition=~models.Q(external_id=""),
            )
        ]

    def __str__(self):
        return f"{self.company_id}:{self.device_id}:{self.device_ts.isoformat()}"


class PunchException(models.Model):
    event = models.OneToOneField(PunchEvent, on_delete=models.CASCADE, related_name="exception")
    kind = models.CharField(
        max_length=40,
        choices=[
            ("face_required_no_match", "face required but no match"),
            ("no_enrollment", "employee has no active face enrollment"),
            ("face_mismatch", "face mismatch"),
            ("outside_scope", "outside scope"),
            ("geofence", "geofence violation"),
        ],
    )
    details = models.JSONField(default=dict)

    def __str__(self):
        return f"{self.event_id}:{self.kind}"
