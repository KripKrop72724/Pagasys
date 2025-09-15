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
