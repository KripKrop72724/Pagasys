from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from pagasys.models import Company, WorkCalendar
from pagasys.tasks import recalc_holiday_roster_entries


class TaskTimezoneTests(TestCase):
    def test_task_activates_company_timezone(self):
        company = Company.objects.create(name="Comp", timezone="Asia/Kolkata")
        cal = WorkCalendar.objects.create(company=company, name="Cal")
        original = timezone.override
        with patch("pagasys.tasks.timezone.override") as mock_override:
            mock_override.side_effect = original
            recalc_holiday_roster_entries(cal.id, [])
            mock_override.assert_called_once()
            zone = getattr(mock_override.call_args[0][0], "key", str(mock_override.call_args[0][0]))
            self.assertEqual(zone, "Asia/Kolkata")

    def test_task_no_calendar_no_override(self):
        with patch("pagasys.tasks.timezone.override") as mock_override:
            recalc_holiday_roster_entries(999, [])
            mock_override.assert_not_called()
