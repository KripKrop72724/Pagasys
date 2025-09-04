# Pagasys Payroll

Pagasys is a human resources and payroll platform focused on the UAE market. It
exposes a fully RESTful API and a scoped Django admin for managing employees,
companies, branches and projects. The project ships with Docker support and a
comprehensive automated test suite.

## Project Overview

* **Visa types** – Employees may have a **company**, **personal**, or **visit** visa.
  Company visas require an associated trade license. Personal and visit visas
  must omit the license and always use cash payments; WPS/C3 identifiers are not
  permitted.
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
* **Shift rule policies** – Geofencing requirements, face match confidence,
  and break enforcement levels (`warn`, `flag`, `auto_deduct`, `block`) keep
  scheduling compliant. Time‑window rules accept ranges that may cross
  midnight (e.g. `22:00-04:00`).
* **Branch & calendar rules** – Branch names are unique per company and trade
  license branches must always belong to the license's company. Employee shift
  rules normalise weekday strings and an `effective_calendar_for()` helper
  resolves the correct work calendar for scheduling.
* **Flexible trade licenses** – Issued and expiry dates are optional. Licenses
  may be either branch‑scoped or global: leave `branches` empty to serve all
  employees in the company or specify branches to limit usage to those
  locations.
* **Company bank accounts** – Each company can record a bank account number for
  payroll deposits. The field is exposed through the API and a dedicated
  "Financial details" section in the admin.
* **Employee notes** – Special notes about employees can be stored and
  managed via the API and Django admin.
* **Employee full names** – Employee records now support separate first,
  middle, and last name fields.
* **Company time zone** – Each company records its IANA time zone (default
  `Asia/Dubai`) so shifts and attendance localise correctly.
* **Leave types** – `paid_pct` uses `Decimal` precision and must be between
  0 and 100. Codes are unique per company regardless of case.
* **Rostering safety** – Employees must have a trade license, department or
  project before they can be assigned to a shift.
* **Archiving over deletion** – Branches, departments and projects linked to
  employees are protected from hard deletion. Mark them inactive to archive
  instead of deleting.
* **Capture layer** – Dedicated app for registering capture devices, face
  enrollment with Amazon Rekognition, and raw punch ingestion with geofence and
  scope validation. Raw events are stored for later summarization by the policy
  layer.

### Capture layer

The capture app records raw attendance punches and manages employee face
enrollments. Face enrollment and image storage require `boto3` and valid AWS
credentials. Images are stored in S3 using the following prefixes:

```
attendance-enroll/{company_id}/{employee_id}/{uuid}.jpg
attendance-capture/{company_id}/{device_id}/{YYYY/MM/DD}/{uuid}.jpg
```

Faces are indexed into Amazon Rekognition collections named
`reko-company-{company_id}`. Punches invoke
`SearchFacesByImage` using a minimum confidence threshold taken from either the
shift rule `FACE_MIN_CONF` or the default setting
`FACE_MATCH_DEFAULT_MIN_CONF` (0.90).

The `rebuild_face_enrollments` management command scans S3 for enrollment
images, reindexes them into Rekognition and writes an Excel report while
logging progress and summarizing any employees with insufficient images.

Two primary endpoints power the workflow:

* `POST /companies/{cid}/employees/{eid}/face/enrollment-link` – generate a
  one‑time link for employees to upload enrollment photos.
* `POST /api/capture/punch` – device endpoint accepting punch metadata and an
  optional image for face verification.
* `GET|POST /companies/{cid}/devices/` – register capture devices and rotate
  API keys.
* `GET /companies/{cid}/punch-events/` – list captured punches with filtering
  and scope enforcement.

All requests from capture devices use the `X-Device-Key` header for
authentication and may optionally provide latitude/longitude for geofence
enforcement.

#### Typical Capture Flow

1. **Register device** – `POST /companies/{cid}/devices/` with a name and optional
   `branch`, `department` or `project` to scope its usage. The response includes an
   `api_key` which the hardware stores and sends in the `X-Device-Key` header.
2. **Generate enrollment link** – managers call
   `POST /companies/{cid}/employees/{eid}/face/enrollment-link` with optional
   `expires_in_hours` and `max_uses` parameters. The returned URL allows an employee
   to upload between 4‑5 images to `/api/face/enroll/{token}`.
3. **Capture punch** – devices submit `POST /api/capture/punch` with punch
   `action`, ISO `timestamp`, optional `employee_id`, `external_id` and GPS
   coordinates (`lat`/`lon`). An image file or `image_b64` payload triggers face
   verification.
4. **Review events** – managers can browse `GET /companies/{cid}/punch-events/`
   or the Django admin to review raw punches and any generated exceptions.

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

Face enrollment and image storage rely on `boto3` and valid AWS credentials.

1. Create a virtual environment and install dependencies:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   ```
2. Copy `.env.example` to `.env` and adjust database credentials.
3. Add AWS Rekognition and S3 settings to `.env`:
   ```
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_REKOGNITION_REGION=ap-south-1
   AWS_S3_BUCKET_ENROLL=your-enroll-bucket
   AWS_S3_BUCKET_CAPTURE=your-capture-bucket
   ```
4. Initialise the database and create groups:
   ```bash
   python manage.py migrate
   python manage.py initgroups
   ```
5. (Optional) Load demo data:
   ```bash
   python manage.py seed
   ```
6. Start the development server:
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

  The application is available at `http://localhost:8000`. Migrations run
  automatically for the web service because `docker-compose.local.yml` sets
  `RUN_MIGRATIONS=1`. The worker service skips migrations by default. The
  Docker image exposes this port by default.

* **`docker-compose.eb.yml`** – defines the web app, worker, Redis, and a
  [Caddy](https://caddyserver.com/) reverse-proxy. Caddy terminates HTTPS on
  ports 80 and 443 and forwards requests to the Django app running on port
  8000. The CI pipeline renames this file to `docker-compose.yml` before
  packaging so Elastic Beanstalk never launches a local PostgreSQL container.
  Only the web container sets `RUN_MIGRATIONS=1`; the worker container runs
  the Celery worker without applying migrations.

For production deployments configure the standard `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, and `DB_HOST` environment variables. The application also honors
an optional `DATABASE_URL` if present, which takes precedence and should include
`sslmode=require`.

### CI/CD database access

GitHub-hosted runners operate on public networks and cannot reach private
database endpoints. When running migrations from the workflow, `DB_HOST` must
resolve publicly or the job must execute from a runner inside your VPC.
The migration step requires these variables:

- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`

Private RDS endpoints therefore need migrations to be triggered from a
network-local environment such as an AWS SSM command or Elastic Beanstalk instance.

### Runtime tuning

Static files are collected during the Docker image build, so rebuild the image after modifying assets.
Gunicorn starts with three workers and a 60 second timeout by default; adjust
`GUNICORN_WORKERS` and `GUNICORN_TIMEOUT` to suit your deployment.
Monitor memory usage during startup and under load with tools like `docker stats`
or `memory_profiler` and optimise routines or increase container memory limits as needed.

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
| `/api/calendars/`   | Company work calendars                   |
| `/api/holidays/`    | Holiday definitions per calendar         |
| `/api/holiday-audit-logs/` | Log of holiday create/update/delete events |
| `/api/shift-templates/` | Reusable shift definitions           |
| `/api/shift-rules/` | Policy rules applied to shifts           |
| `/api/roster-entries/` | Employee shift assignments            |
| `/api/leave-types/` | Leave type configurations                |

### Roster entries

`/api/roster-entries/` provides full control over shift assignments. The
endpoint supports granular filtering, sorting and bulk operations:

* Filters: `employee`, `shift`, `is_rest_day`, `date_from`, `date_to`,
  `branch`, `department` and `project`.
* Ordering: use the `ordering` parameter with `date`, `employee` or `shift`.
* Bulk create/update/delete via `POST roster-entries/bulk`,
  `PATCH roster-entries/bulk-update` and `DELETE roster-entries/bulk-delete`.
* `GET roster-entries/overview?start=<YYYY-MM-DD>&days=<N>` returns a grid of
  entries grouped by employee across the requested date range.
* Entries falling on holidays in the employee's work calendar are
  automatically marked with `is_holiday`. The companion field
  `was_holiday` always records if a scheduled date was a holiday, even when
  `is_holiday` is manually overridden. All roster endpoints – single create,
  `bulk`, policy `bulk-upsert`, and `schedule-range` – populate these flags.
  Supplying `is_holiday` in any request lets you override the automatic
  detection while `was_holiday` preserves the original calendar status.

Example queries:

```http
GET /api/roster-entries/?branch=1&date_from=2024-07-01&date_to=2024-07-31&ordering=employee
PATCH /api/roster-entries/5/ {"is_rest_day": true}
GET /api/roster-entries/overview/?start=2024-07-01&days=7
```

### Policy layer

Endpoints under `/api/companies/<company_id>/` expose a
fully‑scoped attendance policy API. Each resource supports pagination,
ordering and the filters shown below:

| Resource | Path | Filters |
| --- | --- | --- |
| Work calendars | `work-calendars/` | `name`, `is_default` |
| Holidays | `holidays/` | `calendar`, `is_public`, `name`, `date_from`, `date_to` |
| Shift templates | `shift-templates/` | `name`, `cross_midnight`, `requires_face`, `rounding_min` |
| Shift rules | `shift-rules/` | `shift`, `kind`, `active_on`, `weekday` |
| Roster entries | `roster/` | `employee`, `shift`, `is_rest_day`, `date_from`, `date_to`, `branch` |
| Leave types | `leave-types/` | `code`, `requires_doc`, `paid_pct_min`, `paid_pct_max` |

Boolean flags appear throughout the policy models:

* `is_default` – work calendar marked as the company default
* `is_public` – holiday is observed publicly
* `cross_midnight` – shift template spans into the next day
* `requires_face` – employees must face‑match when clocking in
* `params.paid` – a shift rule break counts as paid time
* `is_rest_day` – roster entry is a scheduled rest day
* `requires_doc` – leave type needs supporting documents

All boolean query parameters accept `true` or `false`. Filters are chainable,
allowing queries like:

```http
GET /api/companies/1/holidays?is_public=true&date_from=2024-01-01&date_to=2024-12-31
GET /api/companies/1/shift-templates?requires_face=true
GET /api/companies/1/shift-templates?cross_midnight=true
GET /api/companies/1/roster?is_rest_day=true&date_from=2024-07-01&date_to=2024-07-31
GET /api/companies/1/leave-types?requires_doc=true
```

Custom actions provide additional functionality:

* `GET work-calendars/{id}/holidays` – list holidays for a calendar
* `POST work-calendars/{id}/holidays/import` – bulk import holiday definitions
* `GET shift-templates/{id}/rules` – shortcut for rules on a template
* `GET shift-templates/{id}/preview` – compute duration and rounding info
* `POST shift-rules/validate` – dry‑run rule validation (uses `params.paid`)
* `POST roster/bulk-upsert` – atomic upsert of roster entries
* `POST roster/schedule-range` – assign a shift over a date range with optional rest weekdays
* `GET roster/summary` – aggregate by employee, shift or date

Each list endpoint accepts filters for all model fields and an `ordering` query
parameter. Additional paths include:

* `/api/token/` – obtain JWT access and refresh tokens
* `/api/token/refresh/` – refresh a JWT access token
* `/api/me/` – retrieve the logged-in user's profile
* `/api/schema/` – machine readable OpenAPI schema
* `/api/docs/` – interactive Swagger UI
* `/healthz` – liveness endpoint returning `ok`; `/` responds similarly for load balancer probes

### Roster schedule-range

`POST /api/companies/{company_id}/roster/schedule-range/` creates or updates
consecutive roster entries starting at `start_date`. Supply either `days` (count
of days) or `until` (inclusive end date). Optional `rest_weekdays` accepts
three-letter weekday codes to mark as rest days. Dates that coincide with
calendar holidays are flagged automatically so later payroll calculations can
distinguish holiday work.

Example by number of days:

```http
POST /api/companies/1/roster/schedule-range/
{
  "employee": 1,
  "shift": 3,
  "start_date": "2024-07-01",
  "days": 7,
  "rest_weekdays": ["SAT", "SUN"]
}
```

Example until a date:

```http
POST /api/companies/1/roster/schedule-range/
{
  "employee": 1,
  "shift": 3,
  "start_date": "2024-07-01",
  "until": "2024-07-31"
}
```

Response:

```json
{"count": 31}
```

The `count` equals the number of roster entries created or updated.

## Admin Interface

The admin site uses [Grappelli](https://django-grappelli.readthedocs.io/) for an
improved UI. Querysets and foreign key widgets are restricted so users only see
objects within their role's scope. Trade license and employee forms include
client‑side validation via the JavaScript files in
`pagasys/static/pagasys/js/`. Roster entries can be repeated across multiple
days or until a target date directly from the admin by filling the *repeat* and
*rest weekdays* fields, which automatically mark weekend days as rest days.
For example, to schedule a week's worth of shifts starting 2024‑07‑01 and skip
weekends, set **Repeat days** to `7` and select **Sat** and **Sun** in *Rest
weekdays*. The admin will create entries for the range and flag those days as
rest, mirroring the behaviour of the `schedule-range` API.

## Attendance Policy Layer

The policy layer models how workdays should be structured. It consists of:

* **WorkCalendar** – attaches holiday calendars to a company; a company may have
  zero or one default calendar.
* **Holiday** – individual holiday or company off day linked to a calendar.
* **ShiftTemplate** – reusable definition of a shift including start/end times,
  grace periods, rounding rules and break allowance. Validations enforce
  positive duration, sane break lengths, ordered thresholds and allowed
  rounding increments.
* **ShiftRule** – optional rules that modify a template such as break windows,
  Ramadan reductions or night overtime windows.
* **RosterEntry** – assigns an employee to a shift on a specific date with
  optional one‑day overrides and rest‑day markers.
* **LeaveType** – defines leave codes with paid percentages and documentation
  requirements.

Branches and individual employees may override a company's default calendar
through an optional `work_calendar` field. If no default exists, the field can
still assign a specific calendar. This is useful for regional holiday
differences or role-specific schedules.

Example:

```http
PATCH /api/branches/1/ {"work_calendar": 3}
PATCH /api/employees/42/ {"work_calendar": 3}
```

In the Django admin, the *Work calendar* drop-down only lists calendars owned by
the branch's or employee's company, guiding administrators to select valid
options.

All models participate in the standard scoping and permission system so admins
only manage objects within their company or branch.

### Holiday recalculation

Roster entries created before a holiday is edited or removed may become
out of sync with the latest calendar. Pagasys treats the holiday table as the
source of truth. Any holiday update or deletion automatically enqueues a
Celery task that recalculates `is_holiday`/`was_holiday` flags for roster
entries whose effective calendar matches the changed holiday. Manual overrides
on existing entries are preserved, and an audit log records each holiday change
for traceability. These records are exposed via `/api/holiday-audit-logs/`,
which supports filtering by calendar, action and timestamp range with
custom ordering options.

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

## License

This project is product owned by Sigmoid Solutions LLC.
