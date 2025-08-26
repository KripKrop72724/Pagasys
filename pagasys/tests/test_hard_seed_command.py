from django.core.management import call_command
from django.test import TestCase

from pagasys.models import Employee, Holiday, LeaveType


class HardSeedCommandTests(TestCase):
    def test_hard_seed_creates_demo_data(self):
        """Command should complete and create expected records."""
        call_command("hard_seed", "--force", "--yes", verbosity=0)
        self.assertEqual(Holiday.objects.filter(name="Christmas").count(), 1)
        self.assertEqual(Holiday.objects.count(), 4)
        self.assertEqual(LeaveType.objects.count(), 3)

        self.assertTrue(
            Employee.objects.filter(
                trade_license__isnull=False,
                department__isnull=True,
            ).exists()
        )

        self.assertTrue(
            Employee.objects.filter(
                username="admin",
                is_superuser=True,
                is_staff=True,
            ).exists()
        )

        admin = Employee.objects.get(username="admin")
        self.assertTrue(admin.check_password("admin"))
        