from django.test import Client, TestCase
from django.db.utils import OperationalError
from unittest.mock import patch


class HealthzEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_healthz_returns_ok(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok')

    @patch('pagasys.views.connections')
    def test_healthz_returns_error_when_db_unreachable(self, mock_connections):
        mock_connections.__getitem__.return_value.cursor.side_effect = OperationalError()
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 500)

    @patch('pagasys.views.connections')
    def test_healthz_returns_error_when_query_fails(self, mock_connections):
        cursor = mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = OperationalError()
        response = self.client.get('/healthz/')
        self.assertEqual(response.status_code, 500)
