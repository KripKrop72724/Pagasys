from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_date

from attendance.models import AttDay, AttPair
from attendance.services import build_pairs_for, compute_att_day


class Command(BaseCommand):
    """Recompute days where stray OUT punches inflated late minutes."""

    help = "Rectify attendance days where stray OUT punches inflated late minutes"

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument("--employee-id", type=int, action="append", dest="employee_ids")
        parser.add_argument("--company-id", type=int, action="append", dest="company_ids")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--no-input", action="store_true")

    def handle(self, *args, **options):
        start = parse_date(options["start_date"])
        end = parse_date(options["end_date"])
        if not start or not end or start > end:
            raise CommandError("Invalid date range")

        batch_size: int = options["batch_size"] or 500
        if batch_size <= 0:
            raise CommandError("batch-size must be a positive integer")

        dry_run: bool = options["dry_run"]
        no_input: bool = options["no_input"]
        employee_ids = options.get("employee_ids") or []
        company_ids = options.get("company_ids") or []

        company_filter: Q | None = None
        if company_ids:
            company_filter = (
                Q(employee__trade_license__company_id__in=company_ids)
                | Q(employee__department__branch__company_id__in=company_ids)
                | Q(employee__project__branch__company_id__in=company_ids)
            )

        day_qs = AttDay.objects.filter(date__gte=start, date__lte=end, late_min__gt=0)
        if employee_ids:
            day_qs = day_qs.filter(employee_id__in=employee_ids)
        if company_filter is not None:
            day_qs = day_qs.filter(company_filter)

        candidate_days: dict[tuple[int, date], AttDay] = {
            (day.employee_id, day.date): day for day in day_qs.iterator()
        }

        qs = AttPair.objects.filter(date__gte=start, date__lte=end)
        if employee_ids:
            qs = qs.filter(employee_id__in=employee_ids)
        if company_filter is not None:
            qs = qs.filter(company_filter)
        qs = qs.order_by("employee_id", "date", "in_ts", "id")

        total_pairs = qs.count()
        self.stdout.write(
            f"Scanning {total_pairs} attendance pairs between {start} and {end}"
            f" (batch size {batch_size})"
        )
        if dry_run:
            self.stdout.write("Running in dry-run mode; no changes will be applied.")
        if not no_input:
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() not in {"y", "yes"}:
                self.stdout.write("Aborted.")
                return

        if not candidate_days:
            self.stdout.write("No attendance days with positive late minutes were found.")

        days_checked = 0
        days_recomputed = 0
        days_skipped = 0

        current_key: tuple[int, date] | None = None
        for pair in qs.iterator(chunk_size=batch_size):
            key = (pair.employee_id, pair.date)
            if key == current_key:
                continue
            current_key = key

            day = candidate_days.get(key)
            if not day:
                continue

            anomaly = pair.anomaly or {}
            if "unpaired_out" not in anomaly:
                continue

            days_checked += 1
            if day.locked:
                self.stdout.write(
                    f"Skipping locked day for employee {pair.employee_id} on {pair.date};"
                    " leaving untouched."
                )
                days_skipped += 1
                continue

            message = (
                "Would recompute" if dry_run else "Recomputing"
            ) + (
                f" attendance for employee {pair.employee_id} on {pair.date}"
                f" (late_min={day.late_min})."
            )
            self.stdout.write(message)

            if dry_run:
                days_recomputed += 1
                continue

            with transaction.atomic():
                build_pairs_for(pair.employee_id, pair.date)
                compute_att_day(pair.employee_id, pair.date)
            days_recomputed += 1

        self.stdout.write("Summary:")
        self.stdout.write(f"  Days checked: {days_checked}")
        self.stdout.write(f"  Days recomputed: {days_recomputed}")
        self.stdout.write(f"  Days skipped (locked): {days_skipped}")
        if dry_run:
            self.stdout.write("Dry run complete; no database writes were performed.")
