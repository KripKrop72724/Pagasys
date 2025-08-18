from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import models

from pagasys.models import Employee
from pagasys.tasks_attendance import compute_attday_task


class Command(BaseCommand):
    help = "Backfill attendance days for a company over a date range"

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, required=True)
        parser.add_argument("--from", dest="date_from", required=True)
        parser.add_argument("--to", dest="date_to", required=True)

    def handle(self, *args, **opts):
        company_id = opts["company"]
        date_from = date.fromisoformat(opts["date_from"])
        date_to = date.fromisoformat(opts["date_to"])
        employees = Employee.objects.filter(
            models.Q(trade_license__company_id=company_id)
            | models.Q(department__branch__company_id=company_id)
            | models.Q(project__branch__company_id=company_id)
        )
        cur = date_from
        while cur <= date_to:
            for emp in employees:
                compute_attday_task.delay(company_id, emp.id, cur.isoformat())
            cur += timedelta(days=1)
