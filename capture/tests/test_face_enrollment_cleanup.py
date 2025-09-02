import types

import pytest

from capture.aws import delete_all_employee_faces, company_collection_id
from capture.models import FaceEnrollment
from pagasys.models import Employee
from .test_views import company, branch, department, employee, client  # reuse fixtures
from django.utils import timezone


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, CollectionId):
        for p in self.pages:
            yield p


class FakeRekognitionClient:
    def __init__(self, pages, called):
        self.pages = pages
        self.called = called

    class exceptions:
        class ResourceNotFoundException(Exception):
            pass

    def get_paginator(self, name):
        assert name == "list_faces"
        return FakePaginator(self.pages)

    def delete_faces(self, CollectionId, FaceIds):
        self.called["CollectionId"] = CollectionId
        self.called["FaceIds"] = FaceIds


@pytest.mark.django_db
def test_delete_all_employee_faces_deletes_all(monkeypatch, settings):
    pages = [
        {"Faces": [{"FaceId": "f1", "ExternalImageId": "1"}]},
        {"Faces": [
            {"FaceId": "f2", "ExternalImageId": "1"},
            {"FaceId": "f3", "ExternalImageId": "2"},
        ]},
    ]
    called = {}

    def fake_client(service, region_name=None):
        assert service == "rekognition"
        return FakeRekognitionClient(pages, called)

    monkeypatch.setattr("capture.aws.boto3", types.SimpleNamespace(client=fake_client))
    delete_all_employee_faces(5, 1)
    assert called["CollectionId"] == company_collection_id(5)
    assert called["FaceIds"] == ["f1", "f2"]


@pytest.mark.django_db
def test_delete_all_employee_faces_missing_collection(monkeypatch):
    called = {"delete": False}

    class FakeClient:
        class exceptions:
            class ResourceNotFoundException(Exception):
                pass

        def get_paginator(self, name):
            raise self.exceptions.ResourceNotFoundException

        def delete_faces(self, *a, **k):  # pragma: no cover - should not run
            called["delete"] = True

    def fake_client(service, region_name=None):
        return FakeClient()

    monkeypatch.setattr("capture.aws.boto3", types.SimpleNamespace(client=fake_client))
    delete_all_employee_faces(5, 1)
    assert called["delete"] is False


@pytest.mark.django_db
def test_face_enrollment_model_delete_calls_aws(monkeypatch, employee):
    fe = FaceEnrollment.objects.create(employee=employee, collection_id="c", face_ids=["f1"], status="active")
    called = {}

    def fake_delete(company_id, employee_id):
        called["args"] = (company_id, employee_id)

    monkeypatch.setattr("capture.models.delete_all_employee_faces", fake_delete)
    fe.delete()
    assert called["args"] == (employee.company.id, employee.id)


@pytest.mark.django_db
def test_revoke_endpoint_purges_faces(monkeypatch, client, company, employee):
    FaceEnrollment.objects.create(employee=employee, collection_id="c", face_ids=["f1"], status="active")
    called = {}

    def fake_delete(company_id, employee_id):
        called["args"] = (company_id, employee_id)

    monkeypatch.setattr("capture.models.delete_all_employee_faces", fake_delete)
    monkeypatch.setattr("capture.views.scope_queryset", lambda qs, user: qs)
    monkeypatch.setattr("capture.views.ActionRolePermission.has_permission", lambda *a, **k: True)
    url = f"/api/companies/{company.id}/manage/employees/{employee.id}/face/"
    admin = Employee.objects.create_superuser(
        username="admin", password="pw", hire_date=timezone.localdate(), employment_type="permanent", department=employee.department, visa_type="personal"
    )
    client.force_authenticate(user=admin)
    resp = client.delete(url)
    assert resp.status_code == 204
    assert not FaceEnrollment.objects.filter(employee=employee).exists()
    assert called["args"] == (company.id, employee.id)


@pytest.mark.django_db
def test_revoke_endpoint_no_enrollment(monkeypatch, client, company, employee):
    called = {}

    def fake_delete(company_id, employee_id):
        called["called"] = True

    monkeypatch.setattr("capture.models.delete_all_employee_faces", fake_delete)
    monkeypatch.setattr("capture.views.scope_queryset", lambda qs, user: qs)
    monkeypatch.setattr("capture.views.ActionRolePermission.has_permission", lambda *a, **k: True)
    url = f"/api/companies/{company.id}/manage/employees/{employee.id}/face/"
    admin = Employee.objects.create_superuser(
        username="admin2", password="pw", hire_date=timezone.localdate(), employment_type="permanent", department=employee.department, visa_type="personal"
    )
    client.force_authenticate(user=admin)
    resp = client.delete(url)
    assert resp.status_code == 204
    assert "called" not in called
