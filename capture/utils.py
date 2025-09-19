"""Helper utilities for capture workflows."""

"""Helper utilities for capture workflows."""

from datetime import datetime, timedelta, date as _date, timezone as dt_timezone
from math import radians, sin, cos, sqrt, atan2
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from pagasys.models import (
    RosterEntry,
    ShiftRule,
    ShiftTemplate,
    _minutes_between,
    WEEKDAY_ORDER,
)


def localize_to_company(company, dt_utc: datetime) -> datetime:
    """Convert a UTC datetime to the company's time zone."""
    tz = ZoneInfo(company.timezone)
    if timezone.is_naive(dt_utc):
        dt_utc = timezone.make_aware(dt_utc, dt_timezone.utc)
    return dt_utc.astimezone(tz)


def weekday_code(d: _date) -> str:
    """Return ISO weekday code (MON..SUN)."""
    return WEEKDAY_ORDER[d.weekday()]


def get_face_threshold(shift: ShiftTemplate, roster_day: _date) -> float:
    """FACE_MIN_CONF rule value (0..1) else default."""
    rule = ShiftRule.objects.filter(
        Q(active_from__isnull=True) | Q(active_from__lte=roster_day),
        Q(active_to__isnull=True) | Q(active_to__gte=roster_day),
        shift=shift,
        kind=ShiftRule.Kind.FACE_MIN_CONF,
    ).first()
    try:
        v = float(rule.value) if rule else float(settings.FACE_MATCH_DEFAULT_MIN_CONF)
    except Exception:
        v = float(settings.FACE_MATCH_DEFAULT_MIN_CONF)
    return max(0.0, min(1.0, v))


def compute_roster_date(employee, company_local_dt: datetime):
    """Pick the roster entry whose shift window contains the timestamp.

    Returns a tuple of ``(date, roster_entry, roster_fallback)`` where
    ``roster_fallback`` is ``True`` when no shift window matched and the date
    is based on a fallback lookup.
    """

    d0 = company_local_dt.date()
    candidates = list(
        RosterEntry.objects.filter(employee=employee, date__in=[d0, d0 - timedelta(days=1)]).select_related("shift")
    )
    tzinfo = company_local_dt.tzinfo
    prev_day = d0 - timedelta(days=1)
    same_day_entries: list[RosterEntry] = []
    prev_day_cross: list[RosterEntry] = []
    for cand in sorted(candidates, key=lambda x: x.date, reverse=True):
        s = cand.shift
        start = datetime.combine(cand.date, s.start_time, tzinfo=tzinfo)
        end_date = cand.date + timedelta(days=1 if s.cross_midnight and s.end_time <= s.start_time else 0)
        end = datetime.combine(end_date, s.end_time, tzinfo=tzinfo)
        if start <= company_local_dt <= end:
            return cand.date, cand, False
        if cand.date == d0:
            same_day_entries.append(cand)
        elif cand.date == prev_day and s.cross_midnight:
            prev_day_cross.append(cand)

    next_start: datetime | None = None
    for cand in same_day_entries:
        start = datetime.combine(cand.date, cand.shift.start_time, tzinfo=tzinfo)
        if company_local_dt <= start and (next_start is None or start < next_start):
            next_start = start

    if next_start and prev_day_cross:
        next_gap = next_start - company_local_dt
        best_prev: RosterEntry | None = None
        best_gap: timedelta | None = None
        for cand in prev_day_cross:
            shift = cand.shift
            prev_start = datetime.combine(cand.date, shift.start_time, tzinfo=tzinfo)
            if company_local_dt < prev_start:
                continue
            prev_end_date = cand.date + timedelta(
                days=1 if shift.cross_midnight and shift.end_time <= shift.start_time else 0
            )
            prev_end = datetime.combine(prev_end_date, shift.end_time, tzinfo=tzinfo)
            prev_gap = company_local_dt - prev_end
            if prev_gap.total_seconds() < 0:
                prev_gap = timedelta(0)
            if prev_gap <= next_gap and (best_gap is None or prev_gap < best_gap):
                best_prev = cand
                best_gap = prev_gap
        if best_prev:
            return best_prev.date, best_prev, False

    same = same_day_entries[0] if same_day_entries else None
    return (same.date if same else None), (same or None), True


def within_device_scope(device, employee) -> bool:
    """Check if employee is within device's branch/department/project scope."""
    if device.branch:
        return (
            (employee.department and employee.department.branch_id == device.branch_id)
            or (employee.project and employee.project.branch_id == device.branch_id)
        )
    if device.department:
        return employee.department_id == device.department_id
    if device.project:
        return employee.project_id == device.project_id
    return True


def distance_m(lat1, lon1, lat2, lon2) -> float:
    """Return distance in meters using the haversine formula."""
    R = 6371000.0
    dlat = radians(float(lat2) - float(lat1))
    dlon = radians(float(lon2) - float(lon1))
    a = sin(dlat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


def geofence_ok(device, lat, lon):
    """Return True/False/None depending on geofence evaluation."""
    if not (device.latitude and device.longitude and device.radius_m):
        return True
    if lat is None or lon is None:
        return None
    return distance_m(device.latitude, device.longitude, lat, lon) <= device.radius_m


def get_geofence_requirement(shift: ShiftTemplate, roster_day: _date) -> int | None:
    """Return GEOFENCE_REQUIRED rule value in meters if active for the day."""
    rule = ShiftRule.objects.filter(
        Q(active_from__isnull=True) | Q(active_from__lte=roster_day),
        Q(active_to__isnull=True) | Q(active_to__gte=roster_day),
        shift=shift,
        kind=ShiftRule.Kind.GEOFENCE_REQUIRED,
    ).first()
    try:
        return int(rule.value) if rule else None
    except Exception:
        return None
