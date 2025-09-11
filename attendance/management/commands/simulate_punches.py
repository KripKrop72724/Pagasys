from __future__ import annotations

from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from zoneinfo import ZoneInfo

from attendance.scenarios import ScenarioLibrary
from attendance.services import build_pairs_for, compute_att_day
from capture.models import AttendanceDevice, PunchEvent
from pagasys.models import Employee, RosterEntry, ShiftTemplate, ShiftRule


class Command(BaseCommand):
    help = "Generate punch events for an employee using built-in scenarios"

    def add_arguments(self, parser):
        parser.add_argument("--employee", type=int, required=True)
        parser.add_argument("--start", type=lambda s: datetime.fromisoformat(s).date(), required=True)
        parser.add_argument("--days", type=int, default=1)
        parser.add_argument("--scenarios", type=str, required=True, help="Comma separated names")
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--commit", action="store_true")

    def handle(self, *args, **opts):
        employee = Employee.objects.get(id=opts["employee"])
        start = opts["start"]
        days = opts["days"]
        scenarios = [s.strip() for s in opts["scenarios"].split(",") if s.strip()]
        company = employee.department.branch.company
        device, _ = AttendanceDevice.objects.get_or_create(company=company, name="sim", defaults={"api_key": "sim-key"})

        tz = ZoneInfo(company.timezone)
        with timezone.override(tz):
            for day_offset in range(days):
                day = start + timedelta(days=day_offset)
                for name in scenarios:
                    try:
                        generator = ScenarioLibrary.get(name)
                    except KeyError:
                        raise CommandError(f"Unknown scenario '{name}'")
                    plan = generator(employee, device, day)
                    if opts["dry_run"]:
                        self.stdout.write(
                            f"[DRY RUN] {day} {name}: {len(plan.events)} events"
                        )
                        for ev in plan.events:
                            self.stdout.write(
                                f"  {ev.action} @ {ev.device_ts.isoformat()}"
                            )
                        continue

                    shift = ShiftTemplate.objects.create(**plan.shift_kwargs)
                    for kind, value in plan.rules:
                        ShiftRule.objects.create(shift=shift, kind=kind, value=value)
                    RosterEntry.objects.update_or_create(
                        employee=employee, date=day, defaults={"shift": shift}
                    )
                    PunchEvent.objects.filter(
                        matched_employee=employee, roster_date=day
                    ).delete()
                    PunchEvent.objects.bulk_create(plan.events)
                    build_pairs_for(employee.id, day, shift=shift, tz=tz)
                    compute_att_day(employee.id, day)
                    day_obj = employee.att_days.get(date=day)
                    self.stdout.write(
                        f"{day} {name}: anomalies={day_obj.anomalies} work={day_obj.work_min} late={day_obj.late_min}"
                    )
