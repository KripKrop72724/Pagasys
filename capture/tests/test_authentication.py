import pytest
from rest_framework.test import APIRequestFactory
from rest_framework import exceptions

from capture.authentication import DeviceKeyAuthentication

import pytest
from rest_framework.test import APIRequestFactory
from rest_framework import exceptions

from capture.authentication import DeviceKeyAuthentication
from capture.models import AttendanceDevice
from pagasys.models import Company


@pytest.fixture
def company(db):
    return Company.objects.create(name="Co", timezone="Asia/Dubai")


@pytest.fixture
def device(company):
    return AttendanceDevice.objects.create(company=company, name="dev", api_key="k1")


def test_device_key_authentication_success(device):
    factory = APIRequestFactory()
    request = factory.post("/", HTTP_X_DEVICE_KEY="k1")
    auth = DeviceKeyAuthentication()
    user_auth = auth.authenticate(request)
    assert user_auth == (None, None)
    assert request.device == device
    assert request.company == device.company


def test_device_key_authentication_invalid_key(company):
    AttendanceDevice.objects.create(company=company, name="dev", api_key="good")
    factory = APIRequestFactory()
    request = factory.post("/", HTTP_X_DEVICE_KEY="bad")
    auth = DeviceKeyAuthentication()
    with pytest.raises(exceptions.AuthenticationFailed):
        auth.authenticate(request)


def test_device_key_authentication_missing_header(company):
    AttendanceDevice.objects.create(company=company, name="dev", api_key="k1")
    factory = APIRequestFactory()
    request = factory.post("/")
    auth = DeviceKeyAuthentication()
    assert auth.authenticate(request) is None


def test_device_key_authentication_inactive(company):
    AttendanceDevice.objects.create(company=company, name="dev", api_key="k1", is_active=False)
    factory = APIRequestFactory()
    request = factory.post("/", HTTP_X_DEVICE_KEY="k1")
    auth = DeviceKeyAuthentication()
    with pytest.raises(exceptions.AuthenticationFailed):
        auth.authenticate(request)

