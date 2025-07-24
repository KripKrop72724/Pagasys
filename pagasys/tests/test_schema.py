from django.test import TestCase
from rest_framework.test import APIClient
from pagasys.openapi_utils import _get_filter_fields, document_filters

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

    def test_bulk_response_schemas(self):
        """Bulk endpoints should reference dynamic response serializers."""
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        import json
        data = json.loads(response.content)

        # bulk create
        bulk_post = data['paths']['/api/companies/bulk/']['post']
        first_code, first_resp = next(iter(bulk_post['responses'].items()))
        ref = first_resp['content']['application/json']['schema']['$ref']
        create_schema = data['components']['schemas'][ref.split('/')[-1]]
        self.assertIn('created', create_schema['properties'])
        self.assertIn('errors', create_schema['properties'])

        # bulk delete
        bulk_del = data['paths']['/api/companies/bulk-delete/']['post']
        del_code, del_resp = next(iter(bulk_del['responses'].items()))
        ref = del_resp['content']['application/json']['schema']['$ref']
        del_schema = data['components']['schemas'][ref.split('/')[-1]]
        self.assertIn('deleted', del_schema['properties'])
        self.assertIn('errors', del_schema['properties'])

    def test_model_field_definitions_sync(self):
        """Schema components should mirror serializer fields for all models."""
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code, 200)
        import json
        data = json.loads(response.content)

        from pagasys import serializers as s

        serializer_classes = [
            s.CompanySerializer,
            s.BranchSerializer,
            s.DesignationSerializer,
            s.TradeLicenseSerializer,
            s.DepartmentSerializer,
            s.ProjectSerializer,
            s.EmployeeSerializer,
        ]

        for cls in serializer_classes:
            with self.subTest(serializer=cls.__name__):
                ser_fields = set(cls().get_fields().keys())
                schema_fields = set(
                    data['components']['schemas'][cls.Meta.model.__name__]['properties'].keys()
                )
                self.assertEqual(schema_fields, ser_fields)

    def test_all_filter_parameters_documented(self):
        """Ensure every list endpoint documents its filter parameters."""
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        import json
        data = json.loads(response.content)

        from pagasys import views as v
        from pagasys.openapi_utils import _get_filter_fields

        viewsets = {
            '/api/companies/': v.CompanyViewSet,
            '/api/branches/': v.BranchViewSet,
            '/api/designations/': v.DesignationViewSet,
            '/api/licenses/': v.TradeLicenseViewSet,
            '/api/departments/': v.DepartmentViewSet,
            '/api/projects/': v.ProjectViewSet,
            '/api/employees/': v.EmployeeViewSet,
        }

        for path, viewset in viewsets.items():
            with self.subTest(path=path):
                actual = [p['name'] for p in data['paths'][path]['get']['parameters']]
                expected = _get_filter_fields(viewset)
                for name in expected:
                    self.assertIn(name, actual)
                self.assertIn('ordering', actual)
                self.assertIn('page', actual)

    def test_filter_parameter_description_mentions_compound(self):
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        import json
        data = json.loads(response.content)
        params = data['paths']['/api/companies/']['get']['parameters']
        descriptions = [p['description'] for p in params]
        self.assertTrue(any('compound filtering' in d for d in descriptions))

    def test_filter_examples_in_description(self):
        response = self.client.get('/api/schema/', HTTP_ACCEPT='application/json')
        import json
        data = json.loads(response.content)

        from pagasys import views as v
        from pagasys.openapi_utils import _build_example_query

        cases = {
            '/api/companies/': v.CompanyViewSet,
            '/api/branches/': v.BranchViewSet,
        }

        for path, viewset in cases.items():
            with self.subTest(path=path):
                desc = data['paths'][path]['get']['description']
                example = _build_example_query(viewset)
                self.assertIn(example, desc)

    def test_dynamic_viewset_filters_documented(self):
        from rest_framework import serializers, viewsets, routers
        from django_filters.rest_framework import DjangoFilterBackend
        from drf_spectacular.generators import SchemaGenerator
        from pagasys.openapi_utils import document_filters

        class DummySerializer(serializers.Serializer):
            id = serializers.IntegerField()

        class DummyViewSet(viewsets.ReadOnlyModelViewSet):
            queryset = []
            serializer_class = DummySerializer
            filter_backends = [DjangoFilterBackend]
            filterset_fields = ['foo', 'bar']

        document_filters(DummyViewSet)

        router = routers.SimpleRouter()
        router.register('dummy', DummyViewSet, basename='dummy')

        generator = SchemaGenerator(patterns=router.urls)
        schema = generator.get_schema(request=None, public=True)
        params = schema['paths']['/dummy/']['get']['parameters']
        names = [p['name'] for p in params]
        self.assertIn('foo', names)
        self.assertIn('bar', names)
