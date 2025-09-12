from __future__ import annotations

"""Backfill device timestamps with company timezone.

Usage::

    python manage.py backfill_device_ts_company_local [--batch-size N] [--dry-run]
"""

from django.core.management.base import BaseCommand, CommandError
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from capture.models import PunchEvent
from pagasys.models import Company


class Command(BaseCommand):
    help = "Localize device_ts to the owning company's timezone"

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Do not prompt for confirmation",
        )

    def handle(self, *args, **options):
        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]
        no_input: bool = options["no_input"]

        # Validate company timezones upfront
        invalid_tzs: set[str] = set()
        for tz in Company.objects.values_list("timezone", flat=True).distinct():
            if not tz:
                invalid_tzs.add("<missing>")
                continue
            try:
                ZoneInfo(tz)
            except ZoneInfoNotFoundError:
                invalid_tzs.add(tz)

        if invalid_tzs:
            tz_list = ", ".join(sorted(invalid_tzs))
            raise CommandError(f"Invalid company timezone(s): {tz_list}")

        qs = (
            PunchEvent.objects.select_related("company")
            .filter(device_ts__isnull=False)
            .order_by("id")
        )
        total = qs.count()
        self.stdout.write(
            f"Processing {total} punch events in batches of {batch_size}"
        )
        if not no_input:
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() not in {"y", "yes"}:
                self.stdout.write("Aborted.")
                return

        processed = 0

        for punch in qs.iterator(chunk_size=batch_size):
            try:
                tz = ZoneInfo(punch.company.timezone)
                dt = punch.device_ts
                current_key = getattr(dt.tzinfo, "key", None)
                if dt.tzinfo is None or current_key != tz.key:
                    dt = dt.replace(tzinfo=tz) if dt.tzinfo is None else dt.astimezone(tz)
                    punch.device_ts = dt
                    if not dry_run:
                        punch.save(update_fields=["device_ts"])
            except Exception as exc:  # noqa: BLE001 - continue on error
                self.stderr.write(
                    f"Error processing punch {punch.pk}: {exc}"
                )
                continue

            processed += 1
            if processed % batch_size == 0:
                self.stdout.write(f"Processed {processed}/{total}")

        self.stdout.write(f"Done. Processed {processed}/{total} records.")
