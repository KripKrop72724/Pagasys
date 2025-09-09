from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, date
from typing import List, Tuple

from django.utils import timezone

from capture.models import PunchEvent


@dataclass
class ScenarioPlan:
    """Plan returned by scenario generators.

    Attributes
    ----------
    shift_kwargs: dict
        Parameters used to create the :class:`ShiftTemplate`.
    rules: List[Tuple[str, str]]
        Optional ``(kind, value)`` pairs for ``ShiftRule`` creation.
    events: List[PunchEvent]
        Unsaved ``PunchEvent`` instances that will be stored by the command.
    """

    shift_kwargs: dict
    rules: List[Tuple[str, str]] = field(default_factory=list)
    events: List[PunchEvent] = field(default_factory=list)


class ScenarioLibrary:
    """Factory for punch simulation scenarios."""

    @staticmethod
    def core(employee, device, day: date) -> ScenarioPlan:
        tz = timezone.get_current_timezone()
        out_ts = timezone.make_aware(datetime.combine(day, time(17, 0)), tz)
        ev = PunchEvent(
            device=device,
            company=device.company,
            employee=employee,
            matched_employee=employee,
            action="out",
            device_ts=out_ts,
            roster_date=day,
        )
        shift = dict(
            company=device.company,
            name=f"core-{day.isoformat()}",
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        return ScenarioPlan(shift_kwargs=shift, events=[ev])

    @staticmethod
    def metrics(employee, device, day: date) -> ScenarioPlan:
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(day, time(9, 15)), tz)
        out_ts = timezone.make_aware(datetime.combine(day, time(19, 0)), tz)
        events = [
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="in",
                device_ts=in_ts,
                roster_date=day,
            ),
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="out",
                device_ts=out_ts,
                roster_date=day,
            ),
        ]
        shift = dict(
            company=device.company,
            name=f"metrics-{day.isoformat()}",
            start_time=time(9, 0),
            end_time=time(17, 0),
            late_after_min=0,
            grace_in_min=0,
        )
        return ScenarioPlan(shift_kwargs=shift, events=events)

    @staticmethod
    def break_cross(employee, device, day: date) -> ScenarioPlan:
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(day, time(22, 0)), tz)
        out_ts = timezone.make_aware(datetime.combine(day + timedelta(days=1), time(6, 0)), tz)
        events = [
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="in",
                device_ts=in_ts,
                roster_date=day,
            ),
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="out",
                device_ts=out_ts,
                roster_date=day,
            ),
        ]
        shift = dict(
            company=device.company,
            name=f"break-{day.isoformat()}",
            start_time=time(22, 0),
            end_time=time(6, 0),
            cross_midnight=True,
            break_minutes=60,
        )
        return ScenarioPlan(shift_kwargs=shift, events=events)

    @staticmethod
    def face_geo(employee, device, day: date) -> ScenarioPlan:
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(day, time(9, 0)), tz)
        out_ts = timezone.make_aware(datetime.combine(day, time(17, 0)), tz)
        bad_ts = timezone.make_aware(datetime.combine(day, time(10, 0)), tz)
        events = [
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="in",
                device_ts=in_ts,
                roster_date=day,
            ),
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="out",
                device_ts=out_ts,
                roster_date=day,
                geofence_ok=False,
            ),
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="in",
                device_ts=bad_ts,
                roster_date=day,
                requires_face=True,
                face_matched=False,
            ),
        ]
        shift = dict(
            company=device.company,
            name=f"face-{day.isoformat()}",
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        return ScenarioPlan(shift_kwargs=shift, events=events)

    @staticmethod
    def metadata(employee, device, day: date) -> ScenarioPlan:
        tz = timezone.get_current_timezone()
        in_ts = timezone.make_aware(datetime.combine(day, time(9, 0)), tz)
        out_ts = timezone.make_aware(datetime.combine(day, time(17, 0)), tz)
        events = [
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="in",
                device_ts=in_ts,
                roster_date=day,
                notes="note1",
                external_id="ext1",
            ),
            PunchEvent(
                device=device,
                company=device.company,
                employee=employee,
                matched_employee=employee,
                action="out",
                device_ts=out_ts,
                roster_date=day,
                external_id="ext2",
            ),
        ]
        shift = dict(
            company=device.company,
            name=f"meta-{day.isoformat()}",
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        return ScenarioPlan(shift_kwargs=shift, events=events)

    @classmethod
    def get(cls, name: str):
        try:
            return getattr(cls, name)
        except AttributeError as exc:
            raise KeyError(name) from exc
