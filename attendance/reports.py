"""Attendance reporting utilities."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, date
from typing import Any, Dict, Iterable, List, Tuple

from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.templatetags.static import static

from weasyprint import HTML

from .models import AttDay, AttPair


def get_late_comers(
    start_date: date, end_date: date, filters: Dict[str, Any] | None = None
) -> List[Dict[str, Any]]:
    """Return raw late comer records within the given date range."""

    filters = filters or {}
    qs = AttDay.objects.select_related(
        "employee",
        "employee__department__branch",
        "employee__project__branch",
        "shift",
    ).filter(date__range=(start_date, end_date), late_min__gt=0)

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
        pair = (
            AttPair.objects.filter(employee=day.employee, date=day.date)
            .order_by("in_ts")
            .first()
        )
        actual = timezone.localtime(pair.in_ts) if pair else None
        sched = (
            timezone.make_aware(
                datetime.combine(day.date, day.shift.start_time)
            )
            if day.shift and day.shift.start_time
            else None
        )
        records.append(
            {
                "branch": getattr(day.employee.branch, "name", ""),
                "department": getattr(day.employee.department, "name", ""),
                "project": getattr(day.employee.project, "name", ""),
                "shift": getattr(day.shift, "name", ""),
                "employee": str(day.employee),
                "date": day.date,
                "scheduled_start": sched,
                "actual_arrival": actual,
                "late_min": day.late_min,
            }
        )
    return records


def group_late_comers(records: Iterable[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Group late comer records by branch/department/project/shift."""

    grouped: Dict[str, Any] = {}
    grand_total = 0
    for r in records:
        branch = r["branch"] or "(Unassigned)"
        dept = r["department"] or "(Unassigned)"
        proj = r["project"] or "(Unassigned)"
        shift = r["shift"] or "(Unassigned)"
        late = r["late_min"]
        grand_total += late

        bnode = grouped.setdefault(branch, {"total": 0, "departments": {}})
        bnode["total"] += late
        dnode = bnode["departments"].setdefault(dept, {"total": 0, "projects": {}})
        dnode["total"] += late
        pnode = dnode["projects"].setdefault(proj, {"total": 0, "shifts": {}})
        pnode["total"] += late
        snode = pnode["shifts"].setdefault(shift, {"total": 0, "employees": defaultdict(list)})
        snode["total"] += late

        snode["employees"][r["employee"]].append(
            {
                "date": r["date"],
                "scheduled_start": r["scheduled_start"],
                "actual_arrival": r["actual_arrival"],
                "late_min": late,
            }
        )

    return grouped, {"total_late_min": grand_total}


def render_late_comers_pdf(
    grouped: Dict[str, Any],
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
        "data": grouped,
        "start_date": start_date,
        "end_date": end_date,
        "generated_at": timezone.now(),
        "total_late_min": stats.get("total_late_min", 0),
        "logo_url": logo_url,
    }
    html = render_to_string("reports/late_comers.html", context)
    return HTML(string=html, base_url=base_url).write_pdf()


__all__ = [
    "get_late_comers",
    "group_late_comers",
    "render_late_comers_pdf",
]

