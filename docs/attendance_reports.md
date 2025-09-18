# Late Comers PDF Report

Generate a PDF summary of employees who arrived late within a date range.

## API

`GET /api/companies/{company_id}/att-days/late-comers-report/`

Query parameters:

| name | required | notes |
| ---- | -------- | ----- |
| `start` | yes | `YYYY-MM-DD` inclusive start date |
| `end` | yes | `YYYY-MM-DD` inclusive end date |
| `branch` | no | branch ID filter |
| `department` | no | department ID filter |
| `project` | no | project ID filter |
| `shift` | no | shift template ID filter |

Example:

```bash
curl -L -o late.pdf \
  -H "Authorization: Token <token>" \
  "/api/companies/1/att-days/late-comers-report/?start=2024-01-01&end=2024-01-31"
```

## Admin

Navigate to **Attendance → Att days → Late comers report**. Enter a date range and
optional filters then click **Generate**. The PDF will download directly in your
browser.

## Output

The report groups records by branch, department, project and shift, including
per-level totals and a grand total of late minutes. A header shows the company
logo, date range and generation timestamp.

```
B1 / D1 / (Unassigned) / S1
- E1: 2024-01-01 scheduled 09:00 actual 09:15 late 15
```

## Permissions

Only staff or superuser accounts may access the API or admin view.

## Performance

Late-comer queries use a `(date, late_min)` database index and `select_related`
joins for employee, department, project and shift relations. For very large date
ranges consider chunking the request to avoid excessive memory usage. Concurrent
requests generate PDFs independently and do not share state.

---

# Monthly Attendance PDF Report

Summarise employee attendance for an entire month in a landscape PDF designed
for printing or archival storage. The report groups employees by branch, renders
a compact status grid for each day, and surfaces per-branch as well as
organisation-wide totals.

## API

`GET /api/companies/{company_id}/attendance-calendar/monthly-report/?month=YYYY-MM`

Supported query parameters mirror the calendar API filters:

| name | required | notes |
| ---- | -------- | ----- |
| `month` | yes | `YYYY-MM` month to aggregate |
| `branch` | no | branch ID (repeatable or comma separated) |
| `department` | no | department ID filter |
| `project` | no | project ID filter |
| `employee` | no | restrict to one or more employee IDs |
| `status` | no | comma-separated list of `AttDay.status` values |
| `locked` | no | `true` for locked days, `false` for unlocked |

Example:

```bash
curl -L -o attendance.pdf \
  -H "Authorization: Token <token>" \
  "/api/companies/1/attendance-calendar/monthly-report/?month=2024-05&branch=3"
```

## Admin

Open **Attendance → Att days → Monthly attendance report**. Choose a month and
any optional filters, then click **Generate**. The PDF downloads immediately and
respects the admin user's scope, preventing access to out-of-branch data.

## Output

Each branch section includes the employee count, per-status totals, and a table
with one row per employee. Day cells use glyphs to stay readable when printed:

| Glyph | Meaning | CSS class |
| ----- | ------- | --------- |
| `P` | Present | `.status-present` |
| `A` | Absent / leave | `.status-absent` |
| `R` | Rest / holiday | `.status-rest` |
| `T` | Partial | `.status-partial` |
| `-` | No data | `.status-empty` |

Locked days display a small dot in the corner for quick auditing. A legend at
the bottom of the PDF repeats the glyph mapping and the report header/footers
match the existing late-comers design for consistency.

## Performance

The calendar aggregation is shared with the API, so database access is limited
to scoped `AttDay`, `AttPair`, and `AttAdjustment` queries. Reports stream
directly to WeasyPrint and naturally span multiple pages when branches contain a
large number of employees.
