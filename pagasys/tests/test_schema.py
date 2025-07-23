from django.test import TestCase
from rest_framework.test import APIClient

class OpenAPISchemaTests(TestCase):
    """Validate generated OpenAPI schema and docs."""

    def setUp(self):
        self.client = APIClient()

    def test_schema_endpoint(self):
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        import json
        data = json.loads(response.content)
        self.assertTrue(str(data.get('openapi', '')).startswith('3'))
        models = ['Company', 'Branch', 'Designation', 'TradeLicense', 'Department', 'Project', 'Employee']
        for name in models:
            self.assertIn(name, data['components']['schemas'])
            props = data['components']['schemas'][name]['properties']
            for field, meta in props.items():
                if field == 'id':
                    continue
                self.assertIn('description', meta)
                self.assertTrue(
                    'type' in meta or '$ref' in meta or 'allOf' in meta
                )

    def test_docs_endpoint(self):
        response = self.client.get('/api/docs/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<html', response.content.lower())

    def test_filter_and_pagination_parameters_present(self):
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        import json
        data = json.loads(response.content)
        branch_get = data['paths']['/api/branches/']['get']
        param_names = [p['name'] for p in branch_get['parameters']]
        self.assertIn('ordering', param_names)
        self.assertIn('page', param_names)
        self.assertIn('company', param_names)

    def test_bulk_paths_present(self):
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        import json
        data = json.loads(response.content)
        self.assertIn('/api/companies/bulk/', data['paths'])
        self.assertIn('post', data['paths']['/api/companies/bulk/'])
        self.assertIn('/api/companies/bulk-update/', data['paths'])
        self.assertIn('patch', data['paths']['/api/companies/bulk-update/'])
        self.assertIn('/api/companies/bulk-delete/', data['paths'])
        self.assertIn('post', data['paths']['/api/companies/bulk-delete/'])
