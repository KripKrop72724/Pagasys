import types

import pytest
from django.urls import reverse
from django.utils import timezone

from pagasys.models import Employee

from capture.aws import count_all_faces, delete_all_faces, company_collection_id
from capture.models import FaceEnrollment
from .test_views import company, branch, department, client  # reuse fixtures


class FakePaginator:
    def __init__(self, pages_map):
        self.pages_map = pages_map

    def paginate(self, CollectionId=None):  # type: ignore[override]
        if CollectionId is None:
            for p in self.pages_map.get("__all__", []):
                yield p
        else:
            for p in self.pages_map.get(CollectionId, []):
                yield p


class FakeRekognitionClient:
    def __init__(self, collections_pages, face_pages):
        self.collections_pages = collections_pages
        self.face_pages = face_pages
        self.deleted = []

    def get_paginator(self, name):
        if name == "list_collections":
            return FakePaginator({"__all__": self.collections_pages})
        elif name == "list_faces":
            return FakePaginator(self.face_pages)
        raise AssertionError(name)

    def delete_faces(self, CollectionId, FaceIds):  # pragma: no cover - simple proxy
        self.deleted.append((CollectionId, FaceIds))


@pytest.mark.django_db
def test_count_all_faces(monkeypatch, settings):
    c1 = company_collection_id(1)
    c2 = company_collection_id(2)
    collections = [
        {"CollectionIds": [c1]},
        {"CollectionIds": [c2, "other"]},
    ]
    faces = {
        c1: [{"Faces": [{"FaceId": "a"}]}, {"Faces": [{"FaceId": "b"}]}],
        c2: [{"Faces": [{"FaceId": "c"}, {"FaceId": "d"}]}],
        "other": [{"Faces": [{"FaceId": "ignored"}]}],
    }
    client = FakeRekognitionClient(collections, faces)
    monkeypatch.setattr(
        "capture.aws.boto3",
        types.SimpleNamespace(client=lambda service, region_name=None: client),
    )
    assert count_all_faces() == 4


@pytest.mark.django_db
def test_delete_all_faces(monkeypatch, settings):
    c1 = company_collection_id(1)
    c2 = company_collection_id(2)
    c3 = company_collection_id(3)
    collections = [{"CollectionIds": [c1, c2, c3]}]
    faces = {
        c1: [{"Faces": [{"FaceId": "a"}, {"FaceId": "b"}]}],
        c2: [{"Faces": []}, {"Faces": [{"FaceId": "c"}]}],
        c3: [{"Faces": []}],
    }
    client = FakeRekognitionClient(collections, faces)
    monkeypatch.setattr(
        "capture.aws.boto3",
        types.SimpleNamespace(client=lambda service, region_name=None: client),
    )
    delete_all_faces()
    assert (c1, ["a", "b"]) in client.deleted
    assert (c2, ["c"]) in client.deleted
    assert all(coll != c3 for coll, _ in client.deleted)


@pytest.mark.django_db
def test_admin_changelist_shows_total_and_button(monkeypatch, client, department):
    monkeypatch.setattr("capture.admin.count_all_faces", lambda: 7)
    admin = Employee.objects.create_superuser(
        username="admin",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        department=department,
        visa_type="personal",
    )
    client.force_login(admin)
    resp = client.get(reverse("admin:capture_faceenrollment_changelist"))
    content = resp.content.decode()
    assert "Total AWS face enrollments:" in content
    assert ">7<" in content.replace(" ", "")
    assert "Clear All Face Enrollments" in content


@pytest.mark.django_db
def test_admin_clear_all_faces_view(monkeypatch, client, department):
    called = {}
    monkeypatch.setattr(
        "capture.admin.delete_all_faces", lambda: called.setdefault("called", True)
    )
    monkeypatch.setattr("capture.admin.count_all_faces", lambda: 0)
    monkeypatch.setattr("capture.models.delete_all_employee_faces", lambda *a, **k: None)
    admin = Employee.objects.create_superuser(
        username="admin2",
        password="pw",
        hire_date=timezone.localdate(),
        employment_type="permanent",
        department=department,
        visa_type="personal",
    )
    client.force_login(admin)
    fe = FaceEnrollment.objects.create(employee=admin, collection_id="c", face_ids=["f1"], status="active")
    resp = client.get(reverse("admin:capture_faceenrollment_clear_all_aws_faces"))
    assert resp.status_code == 200
    resp = client.post(
        reverse("admin:capture_faceenrollment_clear_all_aws_faces"),
        {"confirm": "DELETE"},
        follow=True,
    )
    assert called.get("called") is True
    assert resp.status_code == 200
    assert FaceEnrollment.objects.count() == 0

