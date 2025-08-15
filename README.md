# Pagasys Payroll

Pagasys is a human resources and payroll platform focused on the UAE market. It
exposes a fully RESTful API and a scoped Django admin for managing employees,
companies, branches and projects. The project ships with Docker support and a
comprehensive automated test suite.

## Project Overview

* **Visa types** – Employees may have a **company** or **personal** visa. Company
  visas require an associated trade license while personal visas must omit it.
* **Bulk operations** – Every API endpoint supports bulk create, update and
  delete actions in addition to standard CRUD behaviour.
* **Role based access** – Built‑in groups (Company Admin, Branch Manager,
  Payroll Manager, Department Manager, Project Manager and Employee) restrict
  data by company and branch.
* **Dynamic filtering** – All list endpoints accept query parameters for any
  model field. Documentation is automatically generated with
  [`drf-spectacular`](https://drf-spectacular.readthedocs.io/).
* **Admin tooling** – The Django admin limits queryset results according to the
  logged‑in user's scope and provides JavaScript helpers for trade license and
  employee forms.

## Tech Stack

* Python 3.12
* Django 5 with Django REST Framework
* PostgreSQL
* [`drf-spectacular`](https://drf-spectacular.readthedocs.io/) for OpenAPI
  documentation
* [`django-environ`](https://github.com/joke2k/django-environ) for settings
* [`gunicorn`](https://gunicorn.org/) and [`whitenoise`](https://whitenoise.evans.io/)
  for production serving
* [`pytest`](https://pytest.org/) and [`flake8`](https://flake8.pycqa.org/) for
  testing and linting

## Local Development

1. Create a virtual environment and install dependencies:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```
2. Copy `.env.example` to `.env` and adjust database credentials.
3. Initialise the database and create groups:
   ```bash
   python manage.py migrate
   python manage.py initgroups
   ```
4. (Optional) Load demo data:
   ```bash
   python manage.py seed
   ```
5. Start the development server:
   ```bash
   python manage.py runserver
   ```

The API is served under `/api/` and the admin is served under `/admin/`.

## Docker Usage

Two separate Compose files support local development and deployment on Elastic
Beanstalk:

* **`docker-compose.local.yml`** – runs Django and a local PostgreSQL instance.
  After creating an `.env` file, start the stack with:

  ```bash
  docker compose -f docker-compose.local.yml up --build
  ```

  The application is available at `http://localhost:8000` and migrations run
  automatically via `entrypoint.sh`. The Docker image exposes this port by
  default.

* **`docker-compose.eb.yml`** – contains only the web service and exposes it on
  port 80. The CI pipeline renames this file to `docker-compose.yml` before
  packaging so Elastic Beanstalk never launches a local PostgreSQL container.

For production deployments configure the standard `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, and `DB_HOST` environment variables. The application also honors
an optional `DATABASE_URL` if present, which takes precedence and should include
`sslmode=require`.

## API Endpoints

All resources expose standard RESTful endpoints using DRF viewsets:

| Path                | Description                              |
| ------------------- | ---------------------------------------- |
| `/api/companies/`   | Manage companies                         |
| `/api/branches/`    | Manage company branches                  |
| `/api/designations/`| Job designations per company             |
| `/api/licenses/`    | Trade licenses covering branches         |
| `/api/departments/` | Branch departments                       |
| `/api/projects/`    | Branch projects                          |
| `/api/employees/`   | Employee records                         |

Each list endpoint accepts filters for all model fields and an `ordering` query
parameter. Additional paths include:

* `/api/token/` – obtain JWT access and refresh tokens
* `/api/token/refresh/` – refresh a JWT access token
* `/api/schema/` – machine readable OpenAPI schema
* `/api/docs/` – interactive Swagger UI
* `/healthz` – liveness endpoint returning `ok`

## Admin Interface

The admin site uses [Grappelli](https://django-grappelli.readthedocs.io/) for an
improved UI. Querysets and foreign key widgets are restricted so users only see
objects within their role's scope. Trade license and employee forms include
client‑side validation via the JavaScript files in
`pagasys/static/pagasys/js/`.

## Testing & Linting

Run code quality checks with `flake8` and execute the test suite with `pytest`:

```bash
flake8 .
pytest
```

Tests start a PostgreSQL container defined in `tests/docker-compose.yml` via
`pytest-docker`. The configuration for pytest lives in `pytest.ini` and uses the
settings module `config.settings.test`.

## Continuous Integration

GitHub Actions workflow [`ci.yml`](.github/workflows/ci.yml) installs
dependencies, runs `flake8` and `pytest`, then builds and pushes a Docker image
to GitHub Container Registry. Workflow runs trigger on pushes and pull requests
against the `main` branch.

## Linter Configuration

`flake8` rules are defined in [.flake8](.flake8). Line length is capped at 120
characters and several warnings are ignored for brevity. Migrations are excluded
from strict checks.

## Database Seeding

Two custom management commands are available:

* `initgroups` – create default role groups and assign model permissions
* `seed` – populate example companies, branches, departments and employees

They can be run with `python manage.py <command>`.

## Attendance & Leave Schema

Pagasys provides a shift‑based attendance system that intentionally avoids any
`work_branch` field. An employee's branch is derived from their department or
project assignment and all attendance data references the employee directly.

The core models live in `pagasys/models_attendance.py` and include:

* **Device** – registration of kiosk, mobile or web capture devices with an
  HMAC secret and optional geofence.
* **AttEvent** – immutable raw punches (`IN`, `OUT`, `UNK`) with provider
  metadata, liveness scores and signed payload. A partial unique constraint
  prevents duplicate non‑`UNK` punches and an index on `(company, employee, ts)`
  optimises lookups.
* **WorkCalendar / Holiday** – company calendars and their holiday dates.
* **ShiftTemplate** – start/end times, breaks, grace and rounding minutes,
  cross‑midnight handling and a `requires_face` flag. Validation enforces that
  `end_time` is after `start_time` unless `cross_midnight` is enabled.
* **ShiftRule** – per‑company rules such as Ramadan reductions, weekly rest
  days, night OT windows and maximum daily hours.
* **RosterEntry** – unique `(employee, date)` assignments of shift templates.
* **AttPair / AttDay** – processed in/out pairs and daily summaries with
  overtime, lateness and lock flags.
* **LeaveType / LeaveRequest / LeaveDay** – flexible leave tracking supporting
  pay percentages and partial‑day minutes. `LeaveRequest.clean()` ensures the
  date range expands logically.

A small demonstration fixture is available at
`pagasys/fixtures/attendance_seed.json` and can be loaded with:

```bash
python manage.py loaddata pagasys/fixtures/attendance_seed.json
```

The fixture creates a company, calendar with a holiday, two shift templates and
an employee rostered for one week.

## License

This project is product owned by Sigmoid Solutions LLC.
