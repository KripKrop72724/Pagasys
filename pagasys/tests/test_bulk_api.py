from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from pagasys.models import Company


class BulkActionsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="admin", password="pass", is_staff=True, is_superuser=True
        )
        group, _ = Group.objects.get_or_create(name="Company Admin")
        self.user.groups.add(group)
        self.client.force_authenticate(self.user)

    def test_bulk_crud_flow(self):
        create_payload = [{"name": "A"}, {"name": "B"}]
        res = self.client.post("/api/companies/bulk/", create_payload, format="json")
        self.assertEqual(res.status_code, 201)
        ids = [item["id"] for item in res.data["created"]]
        self.assertEqual(len(ids), 2)

        update_payload = [
            {"id": ids[0], "name": "A1"},
            {"id": ids[1], "name": "B1"},
        ]
        res = self.client.patch(
            "/api/companies/bulk-update/", update_payload, format="json"
        )
        self.assertEqual(res.status_code, 200)
        names = [item["name"] for item in res.data["updated"]]
        self.assertEqual(names, ["A1", "B1"])

        # missing id should error
        res = self.client.patch(
            "/api/companies/bulk-update/", [{"name": "bad"}], format="json"
        )
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["errors"]), 1)

        # delete objects
        res = self.client.post("/api/companies/bulk-delete/", ids, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["deleted"], 2)
        self.assertEqual(Company.objects.count(), 0)

        # updating non-existent should 404
        res = self.client.patch(
            "/api/companies/bulk-update/", update_payload, format="json"
        )
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["errors"]), 2)

        # non-list delete payload should error
        res = self.client.post("/api/companies/bulk-delete/", {"id": 1}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_bulk_create_partial_failures(self):
        """Invalid objects in bulk create should return 207 with error details."""
        payload = [{"name": "Valid"}, {}]
        res = self.client.post("/api/companies/bulk/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["created"]), 1)
        self.assertEqual(res.data["created"][0]["name"], "Valid")
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("name", res.data["errors"][0]["errors"])

    def test_bulk_delete_missing_ids(self):
        """Deleting with non-existent ids should still succeed for existing ones."""
        c1 = Company.objects.create(name="DelA")
        payload = [c1.id, 9999]
        res = self.client.post("/api/companies/bulk-delete/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(res.data["deleted"], 1)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertEqual(res.data["errors"][0]["id"], 9999)

    def test_non_list_payload_errors(self):
        """Bulk actions require list payloads."""
        res = self.client.post("/api/companies/bulk/", {"name": "X"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.patch(
            "/api/companies/bulk-update/",
            {"id": 1, "name": "X"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)
