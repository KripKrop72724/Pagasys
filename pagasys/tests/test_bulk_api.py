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

    def test_bulk_delete_multiple_missing_ids(self):
        """A mix of valid and invalid ids should return 207 and detail each missing id."""
        c1 = Company.objects.create(name="DelA")
        payload = [c1.id, 1111, 2222]
        res = self.client.post("/api/companies/bulk-delete/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(res.data["deleted"], 1)
        self.assertEqual(len(res.data["errors"]), 2)
        missing_ids = {err["id"] for err in res.data["errors"]}
        self.assertEqual(missing_ids, {1111, 2222})

    def test_bulk_delete_empty_list(self):
        """Deleting with an empty list succeeds with no action."""
        res = self.client.post("/api/companies/bulk-delete/", [], format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["deleted"], 0)
        self.assertEqual(res.data["errors"], [])

    def test_bulk_delete_invalid_ids(self):
        """Invalid id values should be reported without raising errors."""
        c1 = Company.objects.create(name="DelA")
        payload = [c1.id, "bad", None]
        res = self.client.post("/api/companies/bulk-delete/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(res.data["deleted"], 1)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertEqual(res.data["errors"][0]["id"], "bad")

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

    def test_bulk_create_invalid_types(self):
        """Invalid field types should be reported and skip creation."""
        payload = [{"name": "Good"}, {"name": []}]
        res = self.client.post("/api/companies/bulk/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["created"]), 1)
        self.assertEqual(res.data["created"][0]["name"], "Good")
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("name", res.data["errors"][0]["errors"])

    def test_bulk_update_invalid_types(self):
        """Mixed valid and invalid updates should partially succeed."""
        c1 = Company.objects.create(name="Old")
        c2 = Company.objects.create(name="Bad")
        payload = [
            {"id": c1.id, "name": "New"},
            {"id": c2.id, "name": []},
        ]
        res = self.client.patch("/api/companies/bulk-update/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["updated"]), 1)
        self.assertEqual(res.data["updated"][0]["name"], "New")
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("name", res.data["errors"][0]["errors"])

    def test_bulk_create_unique_conflicts(self):
        comp = Company.objects.create(name="C1")
        payload = [
            {"company": comp.id, "name": "Role"},
            {"company": comp.id, "name": "Role"},
        ]
        res = self.client.post("/api/designations/bulk/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["created"]), 1)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("non_field_errors", res.data["errors"][0]["errors"])

    def test_bulk_update_duplicate_ids(self):
        c = Company.objects.create(name="D")
        payload_create = [
            {"name": "X"},
            {"name": "Y"},
        ]
        res = self.client.post("/api/companies/bulk/", payload_create, format="json")
        ids = [item["id"] for item in res.data["created"]]
        update_payload = [
            {"id": ids[0], "name": "X1"},
            {"id": ids[0], "name": "X2"},
        ]
        res = self.client.patch("/api/companies/bulk-update/", update_payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["updated"]), 1)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("id", res.data["errors"][0]["errors"])

    def test_bulk_update_unique_conflict(self):
        comp = Company.objects.create(name="C2")
        d1 = self.client.post("/api/designations/bulk/", [{"company": comp.id, "name": "A"}, {"company": comp.id, "name": "B"}], format="json")
        ids = [item["id"] for item in d1.data["created"]]
        payload = [
            {"id": ids[0], "name": "Same"},
            {"id": ids[1], "name": "Same"},
        ]
        res = self.client.patch("/api/designations/bulk-update/", payload, format="json")
        self.assertEqual(res.status_code, 207)
        self.assertEqual(len(res.data["updated"]), 1)
        self.assertEqual(len(res.data["errors"]), 1)
        self.assertIn("non_field_errors", res.data["errors"][0]["errors"])
