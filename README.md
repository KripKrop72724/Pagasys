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

## Attendance Computation Layer

The computation layer turns raw punches and policy definitions into
payroll‑ready daily records. It operates on three core models:

* **AttPair** – paired `IN`/`OUT` sessions built from eligible
  `PunchEvent` records. Pairing enforces geofence, face, and scope
  requirements and flags anomalies such as missing outs or duplicate ins.
* **LeaveRequest/LeaveDay** – approved leave is materialised per day so it
  can be overlaid on attendance without recomputing date ranges.
* **AttDay** – the canonical, lockable daily outcome containing work
  minutes, break deductions, overtime buckets, leave portions and
  anomalies. Payroll and reporting consume this table.

### Flow

1. **Punch capture** – devices submit events to `/api/capture/punch`.
2. **Pairing** – a signal enqueues `pair_employee_day_task`, which runs
   `build_pairs_for()` to create `AttPair` rows per employee/day. The
   pairing worker enforces face/geofence/scope rules, resolves
   `auto`/`in`/`out` semantics deterministically and records canonical
   anomalies such as `unpaired_out` or `missing_out_closed_at_next_in`.
3. **Day compute** – `compute_employee_day_task` blends `AttPair`
   sessions with rostered shifts, shift rules, leave, and holidays to
   populate an `AttDay` row. Break rules (`FIXED_BREAK_WINDOW`,
   `REQUIRED_BREAK_AFTER_CONSECUTIVE`, `MIN_TOTAL_BREAK_PER_DAY`,
   `PAID_BREAK_WINDOW`) adjust paid/unpaid minutes, Ramadan reductions
   lower scheduled requirements, overtime minutes are classified with
   Holiday → Night → Regular precedence and `MAX_DAILY_HOURS` caps spill
   extra minutes into OT and log `overtime_over_cap` anomalies.
4. **Adjustments** – approved `AttAdjustment` records apply additive
   deltas and optional status overrides. Creating a manual `AttPair`
   (`POST /companies/{cid}/att-pairs/`) or `AttAdjustment`
   (`POST /companies/{cid}/att-adjustments/`) triggers a recompute for
   the affected day.
5. **Payroll** – once validated, days can be locked to prevent further
   modification. Locked days reject new adjustments and recompute jobs.

### Shift rule resolution

`ShiftRule` rows are filtered per shift and date before computation. The
helper `active_rules(shift, day)` returns only rules whose date ranges and
weekday masks include the target day:

```python
def active_rules(shift, day):
    if not shift:
        return []
    weekday = day.strftime("%a").upper()[:3]
    return list(
        ShiftRule.objects
        .filter(shift=shift)
        .filter(Q(active_from__isnull=True) | Q(active_from__lte=day))
        .filter(Q(active_to__isnull=True) | Q(active_to__gte=day))
        .filter(Q(weekdays="") | Q(weekdays__icontains=weekday))
    )
```

Rules are grouped by kind and applied in the order returned, allowing
seasonal windows (e.g., Ramadan) or weekday‑specific break rules without
manual toggling.

### Auto punch state machine

The pairing worker treats `auto` events deterministically so repeated
recomputes always yield the same sessions:

| Sequence | Resulting pairs | Anomalies |
|----------|-----------------|-----------|
| `IN → AUTO → OUT` | One pair from the first `IN` to the `AUTO`; trailing `OUT` is ignored | `unpaired_out` |
| `AUTO → AUTO` | First `AUTO` opens, second closes the session | — |
| `IN → IN` | Second `IN` closes the first at its timestamp | `missing_out_closed_at_next_in` |
| `OUT` with no open `IN` | No pair recorded | `unpaired_out` |

Any leftover open `IN` is auto‑closed at the scheduled shift end.

### Break rules

Break processing combines shift templates with rule windows to avoid
double deductions:

* **`FIXED_BREAK_WINDOW`** – enforce a minimum break inside a specific time
  range. If an employee works 08:00‑18:00 with a `12:00-13:00`
  fixed window and only logs a 30‑minute break, `auto_deduct`
  enforcement subtracts the missing 30 minutes and records
  `break_auto_deduct_<rule_id>`.
* **`REQUIRED_BREAK_AFTER_CONSECUTIVE`** – after `N` continuous work
  minutes, require a break of `M` minutes. Example: a 300‑minute
  threshold with `M=30` inserts a deduction when an employee works
  5 straight hours.
* **`MIN_TOTAL_BREAK_PER_DAY`** – top up total break time at day end. A
  60‑minute requirement will deduct the shortfall if only 45 minutes
  were taken.
* **`PAID_BREAK_WINDOW`** – minutes inside the window count as paid
  break and do not reduce `work_min`.

#### Configuring rule windows in the admin

All break and night‑OT rules are created via the
[`ShiftRule` admin](/admin/pagasys/shiftrule/). Example setups:

1. **Fixed break window** – `kind="fixed_break_window"`, `value="12:00-13:00"`,
   `params={"paid": false, "enforcement": "auto_deduct", "min_minutes": 60}`.
   Missing minutes are auto‑deducted and logged as
   `break_auto_deduct_<id>`.
2. **Required break after consecutive work** –
   `kind="required_break_after_consecutive"`, `value=300`,
   `params={"minutes": 30, "paid": false, "enforcement": "auto_deduct"}`.
   After five hours of continuous work, 30 minutes are deducted.
3. **Minimum total break per day** –
   `kind="min_total_break_per_day"`, `value=60`,
   `params={"paid": false, "enforcement": "auto_deduct"}`.
   If only 45 minutes are taken, 15 are deducted.
4. **Paid break window** – `kind="paid_break_window"`,
   `value="15:00-15:15"`, `params={"enforcement": "warn"}`. Minutes in the
   window accumulate in `paid_break_min`.
5. **Night overtime window** – `kind="night_ot_window"`,
   `value="22:00-06:00"`. Minutes inside are tallied as `ot_night_min`.

### Overtime and reductions

Overtime classification walks the minute timeline with
Holiday → Night → Regular precedence. A 20:00‑04:00 shift with a
`22:00-06:00` night window yields 120 night minutes (22:00‑00:00 &
00:00‑04:00) and the remainder as regular OT. `MAX_DAILY_HOURS`
spills extra minutes beyond the cap into OT and logs
`overtime_over_cap`.

Ramadan reductions lower the scheduled requirement before
late/early/status evaluation. For example, a 540‑minute shift with a
`RAMADAN_REDUCE_MINUTES=60` rule only requires 480 minutes; arriving 45
minutes late records `late_min=0`.

### Manual adjustments and anomalies

#### Manual pair creation

Missed punches can be corrected by inserting a manual session:

1. In the [`AttPair` admin](/admin/attendance/attpair/add/), choose the
   employee and roster **date**, enter `in_ts` and `out_ts` timestamps, and
   set **source** to "manual". Saving the form queues recomputation for that
   day.
2. Via API, send:

```json
POST /companies/{cid}/att-pairs/
{
  "employee": 1,
  "date": "2024-05-01",
  "in_ts": "2024-05-01T09:00:00+04:00",
  "out_ts": "2024-05-01T17:00:00+04:00",
  "source": "manual"
}
```

The response returns the created pair and recomputation updates the
corresponding `AttDay`.

#### Manual adjustments

`AttAdjustment` records apply additive deltas after computation and may
override the final status.

1. Visit the [`AttAdjustment` admin](/admin/attendance/attadjustment/add/)
   and fill the minute deltas plus an optional `override_status` and reason.
2. Or call `POST /companies/{cid}/att-adjustments/` with a payload such as:

```json
{
  "employee": 1,
  "date": "2024-05-01",
  "delta_work_min": 15,
  "reason": "handover"
}
```

Saving either form recomputes the day and records a
`manual_adjustments_applied` anomaly.

The calculator surfaces a canonical anomaly map on `AttDay`. Common
keys include:

* `face_required_no_match`
* `geofence_rule_violation`
* `outside_scope`
* `unpaired_out`
* `missing_out_closed_at_next_in`
* `break_auto_deduct_<rule_id>`
* `overtime_over_cap`
* `manual_adjustments_applied`

Use `/companies/{cid}/att-days/` or the
[`AttDay` admin](/admin/attendance/attday/) to inspect anomalies and
their impact.

### API Endpoints

All attendance endpoints are documented in the generated Swagger/OpenAPI
schema and live under the company scope:

* `GET /companies/{cid}/att-pairs/` – list paired sessions.
* `POST /companies/{cid}/att-pairs/` – create a manual pair (`in_ts` and
  `out_ts` must be ISO‑8601 timestamps with timezone).
* `GET /companies/{cid}/att-days/` – list computed daily results with
  anomaly maps.
* `POST /companies/{cid}/att-adjustments/` – record manual minute
  deltas and optional status overrides.
* `POST /companies/{cid}/att-days/recompute/` – queue recomputation for a
  date range and optional employees.
* `POST /companies/{cid}/att-days/lock/` – lock or unlock a range of days
  to freeze numbers for payroll.

Each endpoint honours the standard scoping rules so users only see data
within their company or branch.

### Admin Usage

The Django admin exposes dedicated pages for all attendance models:

* [`AttDay` admin](/admin/attendance/attday/) – review computed days and
  run bulk actions **Queue recompute** (recalculate in the background),
  **Lock selected** (freeze totals) and **Unlock selected**.
* [`AttPair` admin](/admin/attendance/attpair/) – inspect individual
  sessions; manual pairs show `source="manual"`.
* [`AttAdjustment` admin](/admin/attendance/attadjustment/) – review or
  edit manual adjustments.

Filters and search fields help administrators quickly locate specific
employees or dates.

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
