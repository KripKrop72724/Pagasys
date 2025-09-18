"""Filtersets for attendance APIs."""

import django_filters as df
from django.db.models import Q

from pagasys.filters import NumberInFilter

from .models import AttDay, AttPair


class AttDayFilter(df.FilterSet):
    """Filters for :class:`AttDay` supporting multi-branch queries."""

    employee = NumberInFilter(field_name="employee_id")
    branch = NumberInFilter(method="filter_branch")
    date = df.DateFilter(field_name="date")
    status = df.CharFilter(field_name="status")
    is_holiday = df.BooleanFilter()
    is_rest_day = df.BooleanFilter()
    locked = df.BooleanFilter()

    def filter_branch(self, queryset, name, value):
        if not value:
            return queryset
        branch_filter = (
            Q(employee__department__branch_id__in=value)
            | Q(employee__project__branch_id__in=value)
        )
        return queryset.filter(branch_filter).distinct()

    class Meta:
        model = AttDay
        fields = ["employee", "date", "status", "is_holiday", "is_rest_day", "locked", "branch"]


class AttPairFilter(df.FilterSet):
    """Filters for :class:`AttPair` including branch lookups."""

    employee = NumberInFilter(field_name="employee_id")
    branch = NumberInFilter(method="filter_branch")
    date = df.DateFilter(field_name="date")
    source = df.CharFilter(field_name="source")

    def filter_branch(self, queryset, name, value):
        if not value:
            return queryset
        branch_filter = (
            Q(employee__department__branch_id__in=value)
            | Q(employee__project__branch_id__in=value)
        )
        return queryset.filter(branch_filter).distinct()

    class Meta:
        model = AttPair
        fields = ["employee", "date", "source", "branch"]
