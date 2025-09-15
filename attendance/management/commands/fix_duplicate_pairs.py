from __future__ import annotations

from datetime import date
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from capture.models import PunchEvent, PunchException
from attendance.models import AttPair, AttDay
from attendance.services import build_pairs_for, compute_att_day


class Command(BaseCommand):
    """Backfill duplicate punch exceptions and rebuild attendance to fix the double punch issue"""

    help = "Backfill duplicate punch exceptions and rebuild attendance pairs"

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-input", action="store_true")
        parser.add_argument("--employee-id", type=int, action="append", dest="employee_ids")
        parser.add_argument("--company-id", type=int, action="append", dest="company_ids")

    def handle(self, *args, **options):
        start = parse_date(options["start_date"])
        end = parse_date(options["end_date"])
        if not start or not end or start > end:
            raise CommandError("Invalid date range")

        batch_size: int = options["batch_size"]
        dry_run: bool = options["dry_run"]
        no_input: bool = options["no_input"]
        emp_ids = options.get("employee_ids")
        company_ids = options.get("company_ids")

        qs = (
            PunchEvent.objects.select_related("exception")
            .filter(
                roster_date__gte=start,
                roster_date__lte=end,
                matched_employee_id__isnull=False,
            )
            .order_by("matched_employee_id", "roster_date", "device_ts", "id")
        )
        if emp_ids:
            qs = qs.filter(matched_employee_id__in=emp_ids)
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)

        total = qs.count()
        self.stdout.write(f"Scanning {total} punch events in batches of {batch_size}")
        if not no_input:
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() not in {"y", "yes"}:
                self.stdout.write("Aborted.")
                return

        prev = None
        prev_key = None
        processed = 0
        exceptions_created = 0
        affected: set[tuple[int, date]] = set()

        for ev in qs.iterator(chunk_size=batch_size):
            key = (ev.matched_employee_id, ev.roster_date)
            if prev and prev_key == key and ev.action == prev.action:
                diff = int((ev.device_ts - prev.device_ts).total_seconds())
                if diff <= 60:
                    try:
                        existing = ev.exception
                    except PunchException.DoesNotExist:
                        existing = None
                    if not existing or existing.kind != "duplicate":
                        if not dry_run:
                            PunchException.objects.create(
                                event=ev,
                                kind="duplicate",
                                details={
                                    "previous_event_id": prev.id,
                                    "diff_seconds": diff,
                                },
                            )
                        exceptions_created += 1
                        affected.add(key)
                        continue
            prev = ev
            prev_key = key
            processed += 1
            if processed % batch_size == 0:
                self.stdout.write(f"Processed {processed}/{total}")

        pairs_rebuilt = 0
        days_recomputed = 0
        for emp_id, day in sorted(affected):
            if AttDay.objects.filter(employee_id=emp_id, date=day, locked=True).exists():
                self.stdout.write(f"Skipping locked day for employee {emp_id} on {day}")
                continue
            if dry_run:
                pairs_rebuilt += AttPair.objects.filter(employee_id=emp_id, date=day).count()
                days_recomputed += 1
                continue
            with transaction.atomic():
                AttPair.objects.filter(employee_id=emp_id, date=day).delete()
                pairs_rebuilt += build_pairs_for(emp_id, day)
                compute_att_day(emp_id, day)
                days_recomputed += 1

        self.stdout.write(
            f"Duplicate exceptions: {exceptions_created}, pairs rebuilt: {pairs_rebuilt}, days recomputed: {days_recomputed}"
        )
