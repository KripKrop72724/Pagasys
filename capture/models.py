import secrets

from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from pagasys.models import Company, Branch, Department, Project, Employee
from .aws import delete_all_employee_faces


class AttendanceDevice(models.Model):
    """Capture device used to record employee punches."""

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="devices",
        help_text="Owning company for the device",
    )
    name = models.CharField(max_length=120, help_text="Human friendly device label")
    api_key = models.CharField(
        max_length=64,
        unique=True,
        help_text="Generated key supplied via the X-Device-Key header",
    )
    is_active = models.BooleanField(
        default=True, help_text="Inactive devices may not submit punches"
    )

    branch = models.ForeignKey(
        Branch,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="devices",
        help_text="Limit device usage to this branch",
    )
    department = models.ForeignKey(
        Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="devices",
        help_text="Limit device usage to this department",
    )
    project = models.ForeignKey(
        Project,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="devices",
        help_text="Limit device usage to this project",
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Geofence latitude in decimal degrees",
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Geofence longitude in decimal degrees",
    )
    radius_m = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Geofence radius in metres",
    )

    last_seen = models.DateTimeField(
        null=True, blank=True, help_text="Last time the device contacted the API"
    )
    note = models.CharField(max_length=255, blank=True, help_text="Internal note")

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
    """Links an employee to stored face templates in AWS Rekognition."""

    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="face_enrollment",
        help_text="Employee that owns the indexed faces",
    )
    collection_id = models.CharField(
        max_length=128, help_text="Rekognition collection identifier"
    )
    face_ids = models.JSONField(
        default=list, help_text="List of Rekognition face IDs for the employee"
    )
    STATUS_CHOICES = [("active", "active"), ("revoked", "revoked"), ("pending", "pending")]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
        help_text="Current enrollment status",
    )
    updated_at = models.DateTimeField(auto_now=True, help_text="Last update timestamp")
    created_at = models.DateTimeField(auto_now_add=True, help_text="Creation timestamp")

    def __str__(self):
        return f"{self.employee_id}:{self.status} ({len(self.face_ids)} faces)"

    def delete(self, *args, **kwargs):
        """Ensure all faces for this employee are removed from Rekognition.

        Deleting the model via the admin previously left residual face data in
        AWS which allowed recognition to continue. Purging the collection here
        guarantees complete removal regardless of how the record is deleted.
        """
        delete_all_employee_faces(self.employee.company.id, self.employee_id)
        super().delete(*args, **kwargs)


class EnrollmentLink(models.Model):
    """One-time link for employees to submit enrollment photos.

    Tokens are generated automatically, guaranteed to be unique and are
    immutable once created. A property exposes the complete public URL that
    may be sent to the employee.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="enrollment_links",
        help_text="Employee who will use this link",
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        help_text="Unique token embedded in the enrollment URL",
    )
    expires_at = models.DateTimeField(help_text="Timestamp when the link expires")
    used_at = models.DateTimeField(
        null=True, blank=True, help_text="When the link was used"
    )
    max_uses = models.PositiveSmallIntegerField(
        default=1, help_text="Maximum times the link may be used"
    )
    uses = models.PositiveSmallIntegerField(
        default=0, help_text="Number of times the link has been used"
    )

    class Meta:
        indexes = [models.Index(fields=["token", "expires_at"])]

    @staticmethod
    def _generate_token() -> str:
        """Generate a unique enrollment token."""
        while True:
            tok = secrets.token_urlsafe(32)
            if not EnrollmentLink.objects.filter(token=tok).exists():
                return tok

    def save(self, *args, **kwargs):
        """Persist the link ensuring a unique, immutable token."""
        if self.pk:
            original = (
                EnrollmentLink.objects.filter(pk=self.pk)
                .values_list("token", flat=True)
                .first()
            )
            if original and self.token != original:
                self.token = original
        else:
            self.token = self._generate_token()
        super().save(*args, **kwargs)

    @property
    def url(self) -> str:
        """Return the full public enrollment URL."""
        return f"{settings.PUBLIC_BASE_URL}/api/face/enroll/{self.token}"

    @property
    def is_valid(self):
        now = timezone.now()
        return (self.used_at is None) and (self.expires_at >= now) and (self.uses < self.max_uses)

    def mark_used(self):
        self.uses += 1
        self.used_at = timezone.now()
        self.save(update_fields=["uses", "used_at"])


class PunchEvent(models.Model):
    """Raw attendance punch captured by a device."""

    device = models.ForeignKey(
        AttendanceDevice,
        on_delete=models.PROTECT,
        related_name="events",
        help_text="Device that recorded the punch",
    )
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, help_text="Owning company"
    )
    employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Employee identifier supplied by the device",
    )
    matched_employee = models.ForeignKey(
        Employee,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="matched_events",
        help_text="Employee matched via face recognition",
    )
    action = models.CharField(
        max_length=8,
        choices=[("in", "in"), ("out", "out"), ("auto", "auto")],
        default="auto",
        help_text="Punch direction supplied by the device",
    )

    device_ts = models.DateTimeField(
        help_text="Timestamp reported by the device"
    )
    server_ts = models.DateTimeField(
        auto_now_add=True, help_text="Timestamp recorded by the server"
    )

    s3_key = models.CharField(
        max_length=300, blank=True, help_text="S3 key where the image is stored"
    )
    image_bytes_sha256 = models.CharField(
        max_length=64, blank=True, help_text="SHA256 hash of the uploaded image"
    )

    face_matched = models.BooleanField(
        default=False, help_text="True when a face match was found"
    )
    face_confidence = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Confidence score from Rekognition",
    )

    roster_date = models.DateField(
        null=True, blank=True, help_text="Resolved roster date for the punch"
    )
    requires_face = models.BooleanField(
        default=False, help_text="Shift required face verification"
    )
    out_of_scope = models.BooleanField(
        default=False, help_text="Employee outside the device's scope"
    )
    geofence_ok = models.BooleanField(
        null=True,
        blank=True,
        default=None,
        help_text="True if the punch was within the device geofence",
    )
    geofence_rule_violation = models.BooleanField(
        default=False, help_text="Device or shift violated geofence rule"
    )
    roster_fallback = models.BooleanField(
        default=False,
        help_text="Roster date was inferred from last punch",
    )
    notes = models.CharField(
        max_length=255, blank=True, help_text="Reason punch was not accepted"
    )

    external_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Optional client supplied identifier to deduplicate events",
    )

    class Meta:
        indexes = [
            models.Index(fields=["company", "employee", "device_ts"]),
            models.Index(fields=["device", "external_id"]),
            models.Index(fields=["roster_date"]),
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
    """Reason a captured punch was flagged for review."""

    event = models.OneToOneField(
        PunchEvent,
        on_delete=models.CASCADE,
        related_name="exception",
        help_text="Punch event that triggered the exception",
    )
    kind = models.CharField(
        max_length=40,
        choices=[
            ("face_required_no_match", "face required but no match"),
            ("no_enrollment", "employee has no active face enrollment"),
            ("face_mismatch", "face mismatch"),
            ("outside_scope", "outside scope"),
            ("geofence", "geofence violation"),
            ("geofence_rule", "geofence rule violation"),
        ],
        help_text="Type of exception encountered",
    )
    details = models.JSONField(
        default=dict, help_text="Additional structured details for debugging"
    )

    def __str__(self):
        return f"{self.event_id}:{self.kind}"
