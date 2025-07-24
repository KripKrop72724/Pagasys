# Pagasys
A payroll solution tailored for the UAE market

## API Filtering

All list endpoints support filtering via query parameters. Available filter fields are documented in the OpenAPI schema and Swagger UI. Multiple filters can be combined to perform compound queries, e.g. `?branch=1&employment_type=temporary`. The documentation is generated dynamically from the viewset configuration, so any changes to filter fields automatically appear in the schema.
Example query strings are included in Swagger UI for each endpoint, illustrating how filters can be compounded.
