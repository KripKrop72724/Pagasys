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


def test_company_collection_id_respects_prefix(settings):
    settings.AWS_REKOGNITION_COLLECTION_PREFIX = "custom"
    assert aws.company_collection_id(7) == "custom-7"


def test_search_face_by_image_retries_missing_collection(monkeypatch, settings):
    settings.AWS_REKOGNITION_COLLECTION_PREFIX = "pref"

    class FakeClient:
        class exceptions:
            class ResourceNotFoundException(Exception):
                pass

        def __init__(self):
            self.calls = 0

        def search_faces_by_image(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise self.exceptions.ResourceNotFoundException()
            return {"args": kwargs}

    client = FakeClient()
    monkeypatch.setattr(
        aws,
        "boto3",
        types.SimpleNamespace(client=lambda name, region_name=None: client),
    )
    called = {}

    def fake_ensure(cid):
        called["cid"] = cid

    monkeypatch.setattr(aws, "ensure_collection", fake_ensure)
    resp = aws.search_face_by_image(3, b"img", 0.5)
    assert client.calls == 2
    assert called["cid"] == "pref-3"
    assert resp["args"]["CollectionId"] == "pref-3"


def test_search_face_by_image_no_retry_when_collection_exists(monkeypatch, settings):
    settings.AWS_REKOGNITION_COLLECTION_PREFIX = "pref"

    class FakeClient:
        class exceptions:
            class ResourceNotFoundException(Exception):
                pass

        def __init__(self):
            self.calls = 0

        def search_faces_by_image(self, **kwargs):
            self.calls += 1
            return {"args": kwargs}

    client = FakeClient()
    monkeypatch.setattr(
        aws,
        "boto3",
        types.SimpleNamespace(client=lambda name, region_name=None: client),
    )
    called = {}

    def fake_ensure(cid):
        called["cid"] = cid

    monkeypatch.setattr(aws, "ensure_collection", fake_ensure)
    resp = aws.search_face_by_image(3, b"img", 0.5)
    assert client.calls == 1
    assert "cid" not in called
    assert resp["args"]["CollectionId"] == "pref-3"
