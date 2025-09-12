from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from capture.models import AttendanceDevice, PunchEvent
from pagasys.models import Company


class BackfillDeviceTsCompanyLocalTests(TestCase):
    def setUp(self) -> None:
        self.company_naive = Company.objects.create(
            name="naive", timezone="Asia/Singapore"
        )
        self.device_naive = AttendanceDevice.objects.create(
            company=self.company_naive, name="devn", api_key="k1"
        )
        self.naive_ts = datetime(2024, 1, 1, 12, 0)
        self.punch_naive = PunchEvent.objects.create(
            device=self.device_naive,
            company=self.company_naive,
            device_ts=self.naive_ts,
        )

        self.company_mismatch = Company.objects.create(
            name="mismatch", timezone="Asia/Tokyo"
        )
        self.device_mismatch = AttendanceDevice.objects.create(
            company=self.company_mismatch, name="devm", api_key="k2"
        )
        self.mismatch_ts = datetime(2024, 1, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
        self.punch_mismatch = PunchEvent.objects.create(
            device=self.device_mismatch,
            company=self.company_mismatch,
            device_ts=self.mismatch_ts,
        )

    def test_dry_run_does_not_save(self) -> None:
        call_command("backfill_device_ts_company_local", dry_run=True, no_input=True)

        self.punch_naive.refresh_from_db()
        self.punch_mismatch.refresh_from_db()

        self.assertEqual(
            self.punch_naive.device_ts,
            self.naive_ts.replace(tzinfo=ZoneInfo("UTC")),
        )
        self.assertEqual(self.punch_mismatch.device_ts, self.mismatch_ts)

    def test_normal_run_localizes_and_saves(self) -> None:
        call_command("backfill_device_ts_company_local", no_input=True)

        self.punch_naive.refresh_from_db()
        self.punch_mismatch.refresh_from_db()

        self.assertEqual(
            self.punch_naive.device_ts,
            self.naive_ts.replace(tzinfo=ZoneInfo("UTC")).astimezone(
                ZoneInfo(self.company_naive.timezone)
            ),
        )
        self.assertEqual(
            self.punch_mismatch.device_ts,
            self.mismatch_ts.astimezone(
                ZoneInfo(self.company_mismatch.timezone)
            ),
        )

    def test_invalid_timezones_are_deduplicated(self) -> None:
        Company.objects.create(name="bad1", timezone="")
        Company.objects.create(name="bad2", timezone="")
        Company.objects.create(name="bad3", timezone="Mars/Phobos")
        Company.objects.create(name="bad4", timezone="Mars/Phobos")

        with self.assertRaises(CommandError) as exc:
            call_command(
                "backfill_device_ts_company_local",
                dry_run=True,
                no_input=True,
            )

        self.assertEqual(
            str(exc.exception),
            "Invalid company timezone(s): <missing>, Mars/Phobos",
        )

