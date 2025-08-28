import hashlib
from datetime import date
import types
import uuid

import pytest

from capture import aws


class DummyS3:
    def __init__(self):
        self.calls = []

    def put_object(self, Bucket, Key, Body, ContentType):
        self.calls.append((Bucket, Key, Body, ContentType))


def test_put_capture_to_s3_uploads_and_hashes(monkeypatch, settings):
    settings.AWS_S3_BUCKET_CAPTURE = "capturebucket"
    dummy_s3 = DummyS3()
    monkeypatch.setattr(
        aws,
        "boto3",
        types.SimpleNamespace(client=lambda name, region_name=None: dummy_s3),
    )
    fake_uuid = uuid.UUID("01234567-89ab-cdef-0123-456789abcdef")
    monkeypatch.setattr(aws.uuid, "uuid4", lambda: fake_uuid)
    monkeypatch.setattr(aws.timezone, "localdate", lambda: date(2023, 3, 4))
    data = b"image bytes"
    key, sha = aws.put_capture_to_s3(1, 2, data)
    expected_key = (
        "attendance-capture/"
        "1/2/2023/03/04/"
        "0123456789abcdef0123456789abcdef.jpg"
    )
    assert key == expected_key
    assert sha == hashlib.sha256(data).hexdigest()
    assert dummy_s3.calls == [
        ("capturebucket", expected_key, data, "image/jpeg")
    ]


def test_put_enroll_to_s3_uploads_and_hashes(monkeypatch, settings):
    settings.AWS_S3_BUCKET_ENROLL = "enrollbucket"
    dummy_s3 = DummyS3()
    monkeypatch.setattr(
        aws,
        "boto3",
        types.SimpleNamespace(client=lambda name, region_name=None: dummy_s3),
    )
    fake_uuid = uuid.UUID("fedcba98-7654-3210-fedc-ba9876543210")
    monkeypatch.setattr(aws.uuid, "uuid4", lambda: fake_uuid)
    data = b"enroll image"
    key, sha = aws.put_enroll_to_s3(3, 4, data)
    expected_key = (
        "attendance-enroll/3/4/fedcba9876543210fedcba9876543210.jpg"
    )
    assert key == expected_key
    assert sha == hashlib.sha256(data).hexdigest()
    assert dummy_s3.calls == [
        ("enrollbucket", expected_key, data, "image/jpeg")
    ]


def test_put_to_s3_requires_boto3(monkeypatch):
    monkeypatch.setattr(aws, "boto3", None)
    with pytest.raises(RuntimeError):
        aws._put_to_s3("bucket", "key", b"data")
