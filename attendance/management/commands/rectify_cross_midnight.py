from __future__ import annotations

from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from attendance.models import AttDay, AttPair
from attendance.services import build_pairs_for, compute_att_day
from capture.models import PunchEvent
from capture.utils import compute_roster_date


class Command(BaseCommand):
    """Reassign late cross-midnight punches and rebuild attendance."""

    help = "Rectify cross-midnight punches that fell back to the following day"

    def add_arguments(self, parser):
        parser.add_argument("--start-date", required=True)
        parser.add_argument("--end-date", required=True)
        parser.add_argument("--company-id", type=int, action="append", dest="company_ids")
        parser.add_argument("--employee-id", type=int, action="append", dest="employee_ids")
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

        qs = (
            PunchEvent.objects.select_related("company", "matched_employee")
            .filter(
                roster_fallback=True,
                matched_employee_id__isnull=False,
                device_ts__date__gte=start,
                device_ts__date__lte=end,
            )
            .order_by("matched_employee_id", "device_ts", "id")
        )
        if employee_ids:
            qs = qs.filter(matched_employee_id__in=employee_ids)
        if company_ids:
            qs = qs.filter(company_id__in=company_ids)

        total = qs.count()
        self.stdout.write(
            f"Inspecting {total} punches between {start} and {end} (batch size {batch_size})"
        )
        if dry_run:
            self.stdout.write("Running in dry-run mode; no changes will be applied.")
        if not no_input:
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() not in {"y", "yes"}:
                self.stdout.write("Aborted.")
                return

        affected_days: dict[int, set[date]] = defaultdict(set)
        updates = 0

        for ev in qs.iterator(chunk_size=batch_size):
            employee = ev.matched_employee
            if not employee:
                continue
            tz = ZoneInfo(ev.company.timezone)
            local_ts = ev.device_ts
            if timezone.is_naive(local_ts):
                local_ts = timezone.make_aware(local_ts, timezone.utc)
            local_ts = local_ts.astimezone(tz)
            new_date, _, new_fallback = compute_roster_date(employee, local_ts)
            if new_date == ev.roster_date and bool(new_fallback) == bool(ev.roster_fallback):
                continue

            updates += 1
            self.stdout.write(
                (
                    "Would update" if dry_run else "Updating"
                )
                + f" punch {ev.id} (employee {employee.id}) from {ev.roster_date}"
                + f" fallback={ev.roster_fallback} to {new_date} fallback={bool(new_fallback)}"
            )

            if ev.roster_date:
                affected_days[employee.id].add(ev.roster_date)
            if new_date:
                affected_days[employee.id].add(new_date)

            if not dry_run:
                PunchEvent.objects.filter(pk=ev.pk).update(
                    roster_date=new_date,
                    roster_fallback=bool(new_fallback),
                )

        if not updates:
            self.stdout.write("No punches required rectification.")

        pairs_rebuilt = 0
        days_recomputed = 0
        locked_days = 0

        for emp_id in sorted(affected_days):
            for day in sorted(affected_days[emp_id]):
                if AttDay.objects.filter(employee_id=emp_id, date=day, locked=True).exists():
                    self.stdout.write(
                        f"Skipping locked day for employee {emp_id} on {day}; leaving untouched."
                    )
                    locked_days += 1
                    continue
                if dry_run:
                    pair_count = AttPair.objects.filter(employee_id=emp_id, date=day).count()
                    self.stdout.write(
                        f"Would rebuild attendance for employee {emp_id} on {day}"
                        f" (would delete {pair_count} existing pairs)."
                    )
                    days_recomputed += 1
                    continue
                self.stdout.write(
                    f"Rebuilding attendance for employee {emp_id} on {day}."
                )
                with transaction.atomic():
                    deleted_count, _ = AttPair.objects.filter(
                        employee_id=emp_id, date=day
                    ).delete()
                    rebuilt = build_pairs_for(emp_id, day)
                    compute_att_day(emp_id, day)
                self.stdout.write(
                    f"Deleted {deleted_count} pairs; rebuilt {rebuilt} pairs for employee {emp_id} on {day}."
                )
                pairs_rebuilt += rebuilt
                days_recomputed += 1

        self.stdout.write("Summary:")
        self.stdout.write(f"  Punches updated: {updates}")
        self.stdout.write(f"  Days recomputed: {days_recomputed}")
        self.stdout.write(f"  Locked days skipped: {locked_days}")
        if not dry_run:
            self.stdout.write(f"  Pairs rebuilt: {pairs_rebuilt}")
        else:
            self.stdout.write("Dry run complete; no database writes were performed.")
