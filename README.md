# Pagasys
A payroll solution tailored for the UAE market

## Visa Types

Employees can now be registered with either a **company** visa or a **personal** visa.
When `visa_type` is set to `company`, a trade license must be selected and the
license's company must match the employee's branch company. For `personal`
visas the trade license field is hidden in the admin and must remain empty.

## API Filtering

All list endpoints support filtering via query parameters. Available filter fields are documented in the OpenAPI schema and Swagger UI. Multiple filters can be combined to perform compound queries, e.g. `?branch=1&employment_type=temporary`. The documentation is generated dynamically from the viewset configuration, so any changes to filter fields automatically appear in the schema.
