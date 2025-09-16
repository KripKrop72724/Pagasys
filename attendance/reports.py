"""Attendance reporting utilities."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Tuple

from django.contrib.staticfiles import finders
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.templatetags.static import static

from weasyprint import HTML, CSS

from .models import AttDay


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

    records: List[Dict[str, Any]] = []
    for day in qs:
        records.append(
            {
                "employee": str(day.employee),
                "shift": getattr(day.shift, "name", ""),
                "date": day.date,
                "late_min": day.late_min,
            }
        )
    return records


def group_late_comers(
    records: Iterable[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Sort records and compute aggregate late minutes."""

    records = list(records)
    records.sort(key=lambda r: (r["employee"], r["date"]))
    total = sum(r["late_min"] for r in records)
    return records, {"total_late_min": total}


def render_late_comers_pdf(
    records: List[Dict[str, Any]],
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
        "data": records,
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


__all__ = [
    "get_late_comers",
    "group_late_comers",
    "render_late_comers_pdf",
]

