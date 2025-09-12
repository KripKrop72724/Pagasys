import pytest
from django.utils import timezone

from capture.tasks import finalize_punch
from capture.models import PunchEvent, AttendanceDevice
from pagasys.models import Company, Branch


@pytest.fixture
def company(db):
    return Company.objects.create(name="Co", timezone="Asia/Dubai")


@pytest.fixture
def branch(company):
    return Branch.objects.create(company=company, name="B1")


@pytest.fixture
def device(company, branch):
    return AttendanceDevice.objects.create(
        company=company, name="dev", api_key="k1", branch=branch
    )


def test_finalize_punch_marks_processed(device):
    ev = PunchEvent.objects.create(
        device=device,
        company=device.company,
        action="in",
        device_ts=timezone.now(),
    )
    assert not ev.processed
    finalize_punch.apply(args=[ev.id])
    ev.refresh_from_db()
    assert ev.processed and ev.processed_at is not None


def test_finalize_punch_retry(monkeypatch, device):
    ev = PunchEvent.objects.create(
        device=device,
        company=device.company,
        action="in",
        device_ts=timezone.now(),
    )
    calls = {"n": 0}
    orig_save = PunchEvent.save

    def flaky_save(self, *a, **kw):
        if calls["n"] == 0:
            calls["n"] += 1
            raise Exception("boom")
        return orig_save(self, *a, **kw)

    monkeypatch.setattr(PunchEvent, "save", flaky_save)
    finalize_punch.apply(args=[ev.id], throw=False)
    ev.refresh_from_db()
    assert ev.processed
    assert calls["n"] == 1
