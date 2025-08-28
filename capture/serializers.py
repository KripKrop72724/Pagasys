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
    api_key = serializers.CharField()


class FaceEnrollmentStatusSerializer(serializers.ModelSerializer):
    faces = serializers.SerializerMethodField()

    class Meta:
        model = FaceEnrollment
        fields = ["status", "faces", "updated_at", "created_at"]

    def get_faces(self, obj):
        return len(obj.face_ids)


class EnrollmentLinkCreateSerializer(serializers.Serializer):
    expires_in_hours = serializers.IntegerField(required=False, min_value=1, max_value=168, default=24)
    max_uses = serializers.IntegerField(required=False, min_value=1, max_value=5, default=1)


class EnrollmentSubmitSerializer(serializers.Serializer):
    images = serializers.ListField(
        child=serializers.ImageField(allow_empty_file=False, use_url=False),
        allow_empty=False,
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
    employee_id = serializers.IntegerField(required=False)
    action = serializers.ChoiceField(choices=["in", "out", "auto"], default="auto")
    timestamp = serializers.DateTimeField()
    external_id = serializers.CharField(required=False, allow_blank=True)
    lat = serializers.FloatField(required=False)
    lon = serializers.FloatField(required=False)


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
