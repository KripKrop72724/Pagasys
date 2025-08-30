from rest_framework import serializers
from django.conf import settings
from pagasys.models import Employee
from .models import AttendanceDevice, FaceEnrollment, EnrollmentLink, PunchEvent


class AttendanceDeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceDevice
        fields = [
            "id",
            "company",
            "name",
            "api_key",
            "is_active",
            "branch",
            "department",
            "project",
            "latitude",
            "longitude",
            "radius_m",
            "last_seen",
            "note",
        ]
        read_only_fields = ["api_key", "last_seen", "company"]


class RotateKeyResponseSerializer(serializers.Serializer):
    api_key = serializers.CharField(help_text="Newly generated API key")


class FaceEnrollmentStatusSerializer(serializers.ModelSerializer):
    faces = serializers.SerializerMethodField()

    class Meta:
        model = FaceEnrollment
        fields = ["status", "faces", "updated_at", "created_at"]

    def get_faces(self, obj):
        return len(obj.face_ids)


class EnrollmentLinkCreateSerializer(serializers.Serializer):
    expires_in_hours = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=168,
        default=24,
        help_text="Hours until the link expires",
    )
    max_uses = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=5,
        default=1,
        help_text="Number of times the link may be used",
    )


class EnrollmentSubmitSerializer(serializers.Serializer):
    images = serializers.ListField(
        child=serializers.ImageField(allow_empty_file=False, use_url=False),
        allow_empty=False,
        help_text="List of enrollment images",
    )

    def validate_images(self, value):
        min_photos = getattr(settings, "FACE_ENROLL_MIN_PHOTOS", 4)
        max_photos = getattr(settings, "FACE_ENROLL_MAX_PHOTOS", 5)
        if not (min_photos <= len(value) <= max_photos):
            raise serializers.ValidationError(
                f"Provide between {min_photos} and {max_photos} images"
            )
        return value


class PunchRequestSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(
        required=False, help_text="Employee ID hint from the device"
    )
    action = serializers.ChoiceField(
        choices=["in", "out", "auto"],
        default="auto",
        help_text="Punch direction",
    )
    timestamp = serializers.DateTimeField(help_text="Device timestamp in ISO format")
    external_id = serializers.CharField(
        required=False, allow_blank=True, help_text="Client supplied ID to deduplicate"
    )
    lat = serializers.FloatField(required=False, help_text="Latitude of device location")
    lon = serializers.FloatField(required=False, help_text="Longitude of device location")
    image = serializers.ImageField(
        required=False,
        allow_empty_file=False,
        use_url=False,
        help_text="Captured image file",
    )
    image_b64 = serializers.CharField(
        required=False,
        help_text="Base64-encoded image if file upload isn't possible",
    )


class PunchResponseSerializer(serializers.Serializer):
    accepted = serializers.BooleanField()
    roster_date = serializers.DateField(required=False, allow_null=True)
    matched_employee = serializers.IntegerField(required=False, allow_null=True)
    face_confidence = serializers.FloatField(required=False, allow_null=True)
    face_mismatch = serializers.BooleanField()
    requires_face = serializers.BooleanField()
    out_of_scope = serializers.BooleanField()
    geofence_ok = serializers.BooleanField(required=False, allow_null=True)
    geofence_rule_violation = serializers.BooleanField()
    roster_fallback = serializers.BooleanField()
    notes = serializers.CharField(required=False, allow_blank=True)
    event_id = serializers.IntegerField()


class EnrollmentLinkResponseSerializer(serializers.Serializer):
    url = serializers.URLField()
    token = serializers.CharField()
    expires_at = serializers.DateTimeField()


class EnrollmentSubmitResponseSerializer(serializers.Serializer):
    faces_indexed = serializers.IntegerField()


class PunchEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PunchEvent
        fields = [
            "id",
            "company",
            "device",
            "employee",
            "matched_employee",
            "action",
            "device_ts",
            "server_ts",
            "face_matched",
            "face_confidence",
            "roster_date",
            "requires_face",
            "out_of_scope",
            "geofence_ok",
            "geofence_rule_violation",
            "roster_fallback",
            "notes",
            "external_id",
        ]
        read_only_fields = fields
