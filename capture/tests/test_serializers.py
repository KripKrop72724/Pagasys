import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
import io

from capture.serializers import EnrollmentSubmitSerializer


def make_image(name: str = "f.jpg"):
    img = Image.new("RGB", (1, 1), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/jpeg")


@override_settings(FACE_ENROLL_MIN_PHOTOS=4, FACE_ENROLL_MAX_PHOTOS=5)
@pytest.mark.django_db
def test_enrollment_photo_count_valid():
    ser = EnrollmentSubmitSerializer(data={"images": [make_image() for _ in range(4)]})
    assert ser.is_valid()
    ser = EnrollmentSubmitSerializer(data={"images": [make_image() for _ in range(5)]})
    assert ser.is_valid()


@override_settings(FACE_ENROLL_MIN_PHOTOS=4, FACE_ENROLL_MAX_PHOTOS=5)
@pytest.mark.django_db
def test_enrollment_photo_count_invalid():
    ser = EnrollmentSubmitSerializer(data={"images": [make_image() for _ in range(3)]})
    assert not ser.is_valid()
    ser = EnrollmentSubmitSerializer(data={"images": [make_image() for _ in range(6)]})
    assert not ser.is_valid()
