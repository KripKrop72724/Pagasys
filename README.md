# Pagasys
A payroll solution tailored for the UAE market

## Visa Types

Employees can now be registered with either a **company** visa or a **personal** visa.
When `visa_type` is set to `company`, a trade license must be selected and the
license's company must match the employee's branch company. For `personal`
visas the trade license field is hidden in the admin and must remain empty.

## API Filtering

All list endpoints support filtering via query parameters. Every API viewset exposes filters for **all** of its model fields, so you can chain together any combination to narrow results. Available fields are documented in the OpenAPI schema and Swagger UI. For example `?branch=1&employment_type=temporary`. Because the documentation is generated from the viewset configuration, any change to filter fields automatically appears in the schema.
## Admin Filtering

All models expose comprehensive filters in the Django admin interface. Use the sidebar filters to quickly narrow results by any field.

## Running with Docker

The project ships with a `Dockerfile` and `docker-compose.yml` for local development. First create an `.env` file based on the provided example and build the images:

```bash
docker-compose build
docker-compose up
```

The web application will be available on `http://localhost:8000` and will automatically run database migrations on start.

## Running Tests

Tests rely on [`pytest`](https://pytest.org), [`pytest-django`](https://pytest-django.readthedocs.io/) and [`pytest-docker`](https://github.com/avast/pytest-docker) to launch a PostgreSQL container. To execute the suite locally ensure Docker is installed and run:

```bash
pip install -r requirements.txt
pytest
```

`pytest-docker` automatically starts the services defined in `pagasys/tests/docker-compose.yml` and configures the necessary environment variables for Django.
