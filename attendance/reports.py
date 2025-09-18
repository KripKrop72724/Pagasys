"""Attendance reporting utilities."""

from __future__ import annotations

from collections import defaultdict, OrderedDict
from datetime import date
from typing import Any, Dict, Iterable, List, Tuple

from django.contrib.staticfiles import finders
from django.db.models import Q, Min
from django.template.loader import render_to_string
from django.utils import timezone
from django.templatetags.static import static

from weasyprint import HTML, CSS

from .models import AttDay, AttPair


def get_late_comers(
    start_date: date, end_date: date, filters: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """Return raw late comer records within the given date range."""

    filters = filters or {}
    qs = (
        AttDay.objects.select_related(
            "employee",
            "employee__department__branch",
            "employee__project__branch",
            "shift",
        )
        .filter(date__range=(start_date, end_date), late_min__gt=0)
        .order_by("employee__first_name", "employee__last_name", "date")
    )

    branch_id = filters.get("branch_id")
    if branch_id:
        qs = qs.filter(
            Q(employee__department__branch_id=branch_id)
            | Q(employee__project__branch_id=branch_id)
        )
    dept_id = filters.get("department_id")
    if dept_id:
        qs = qs.filter(employee__department_id=dept_id)
    proj_id = filters.get("project_id")
    if proj_id:
        qs = qs.filter(employee__project_id=proj_id)
    shift_id = filters.get("shift_id")
    if shift_id:
        qs = qs.filter(shift_id=shift_id)

    days = list(qs)
    if not days:
        return []

    employee_ids = {day.employee_id for day in days}
    punch_map: Dict[Tuple[int, date], Any] = {}
    if employee_ids:
        punches = (
            AttPair.objects.filter(
                employee_id__in=employee_ids, date__range=(start_date, end_date)
            )
            .values("employee_id", "date")
            .annotate(first_in=Min("in_ts"))
        )
        punch_map = {
            (punch["employee_id"], punch["date"]): punch["first_in"]
            for punch in punches
        }

    records: List[Dict[str, Any]] = []
    for day in days:
        branch = day.employee.branch
        records.append(
            {
                "employee": f"{day.employee.first_name} {day.employee.last_name}".strip(),
                "employee_id": day.employee_id,
                "shift": getattr(day.shift, "name", ""),
                "shift_start": getattr(day.shift, "start_time", None),
                "shift_end": getattr(day.shift, "end_time", None),
                "punch_in": punch_map.get((day.employee_id, day.date)),
                "date": day.date,
                "late_min": day.late_min,
                "branch": getattr(branch, "name", "Unassigned"),
            }
        )
    return records


def group_late_comers(
    records: Iterable[Dict[str, Any]]
) -> Tuple["OrderedDict[str, Dict[str, Any]]", Dict[str, Any]]:
    """Group records by branch and compute aggregate late minutes."""

    records = list(records)
    branches: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        branch_name = record.get("branch") or "Unassigned"
        branches[branch_name].append(record)

    grouped: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    total_late = 0
    for branch_name in sorted(branches):
        branch_records = branches[branch_name]
        branch_records.sort(key=lambda r: (r["employee"], r["date"]))
        branch_total = sum(r["late_min"] for r in branch_records)
        grouped[branch_name] = {
            "records": branch_records,
            "total_late_min": branch_total,
        }
        total_late += branch_total

    return grouped, {"total_late_min": total_late}


def render_late_comers_pdf(
    branches: "OrderedDict[str, Dict[str, Any]]",
    stats: Dict[str, Any],
    start_date: date,
    end_date: date,
    request=None,
) -> bytes:
    """Render the late comers report as a PDF."""

    logo_url = static("images/logo.png")
    base_url = None
    if request and hasattr(request, "build_absolute_uri"):
        logo_url = request.build_absolute_uri(logo_url)
        base_url = request.build_absolute_uri("/")

    context = {
        "branches": branches,
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": timezone.now(),
        "total_late_min": stats.get("total_late_min", 0),
        "logo_url": logo_url,
    }
    html = render_to_string("reports/late_comers.html", context)
    stylesheet_path = finders.find("attendance/css/reports.css")
    stylesheets = [CSS(filename=stylesheet_path)] if stylesheet_path else None
    return HTML(string=html, base_url=base_url).write_pdf(stylesheets=stylesheets)


def render_monthly_attendance_pdf(report, context=None):
    """Render the monthly attendance grid as a PDF document."""

    context = context or {}
    request = context.get("request")
    base_url = None
    if request and hasattr(request, "build_absolute_uri"):
        base_url = request.build_absolute_uri("/")

    template_context = {
        "report": report,
        "title": context.get("title", "Monthly attendance report"),
        "company": context.get("company"),
        "filters": context.get("filters", {}),
        "generated_at": context.get("generated_at", timezone.now()),
    }
    html = render_to_string("reports/monthly_attendance.html", template_context)
    stylesheet_path = finders.find("attendance/css/reports.css")
    stylesheets = [CSS(filename=stylesheet_path)] if stylesheet_path else None
    return HTML(string=html, base_url=base_url).write_pdf(stylesheets=stylesheets)


__all__ = [
    "get_late_comers",
    "group_late_comers",
    "render_late_comers_pdf",
    "render_monthly_attendance_pdf",
]

