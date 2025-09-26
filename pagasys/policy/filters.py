import django_filters as df
from django.db.models import Q
from pagasys.models import WorkCalendar, Holiday, ShiftTemplate, ShiftRule, RosterEntry, LeaveType

class DateRange(df.FilterSet):
    date_from = df.DateFilter(field_name="date", lookup_expr="gte")
    date_to = df.DateFilter(field_name="date", lookup_expr="lte")

class WorkCalendarFilter(df.FilterSet):
    name = df.CharFilter(field_name="name", lookup_expr="icontains")
    is_default = df.BooleanFilter()

    class Meta:
        model = WorkCalendar
        fields = ["name", "is_default"]

class HolidayFilter(DateRange):
    name = df.CharFilter(field_name="name", lookup_expr="icontains")
    is_public = df.BooleanFilter()
    calendar = df.NumberFilter(field_name="calendar_id")
    on_date = df.DateFilter(method="filter_on_date")

    def filter_on_date(self, qs, name, value):
        return qs.filter(date=value)

    class Meta:
        model = Holiday
        fields = ["calendar", "is_public", "name"]

class ShiftTemplateFilter(df.FilterSet):
    name = df.CharFilter(field_name="name", lookup_expr="icontains")
    cross_midnight = df.BooleanFilter()
    requires_face = df.BooleanFilter()
    rounding_min = df.NumberFilter()

    class Meta:
        model = ShiftTemplate
        fields = ["name", "cross_midnight", "requires_face", "rounding_min"]

class ShiftRuleFilter(df.FilterSet):
    shift = df.NumberFilter(field_name="shift_id")
    # `kind` values are stored as plain strings on the model.  While the
    # `ShiftRule.Kind` enum documents the supported built-in values, the API
    # shouldn't reject arbitrary strings.  Using a ``ChoiceFilter`` here causes
    # django-filter to validate the query parameter against the enum choices and
    # raise a ``ValidationError`` for unknown kinds.  The API tests expect that
    # filtering with any value simply performs an exact lookup (returning an
    # empty result if nothing matches) rather than responding with *400 Bad
    # Request*.  Switching to a simple ``CharFilter`` removes that validation and
    # allows free-form kind strings while still supporting the documented ones.
    kind = df.CharFilter(field_name="kind")
    active_on = df.DateFilter(method="filter_active_on")
    weekday = df.CharFilter(method="filter_weekday")

    class Meta:
        model = ShiftRule
        fields = ["shift", "kind"]

    def filter_active_on(self, qs, name, value):
        return qs.filter(
            Q(active_from__isnull=True) | Q(active_from__lte=value),
            Q(active_to__isnull=True) | Q(active_to__gte=value),
        )

    def filter_weekday(self, qs, name, value):
        v = value.strip().upper()
        if v not in {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}:
            return qs.none()
        return qs.filter(Q(weekdays__icontains=v) | Q(weekdays=""))

class RosterFilter(df.FilterSet):
    employee = df.NumberFilter(field_name="employee_id")
    shift = df.NumberFilter(field_name="shift_id")
    is_rest_day = df.BooleanFilter()
    date_from = df.DateFilter(field_name="date", lookup_expr="gte")
    date_to = df.DateFilter(field_name="date", lookup_expr="lte")
    branch = df.NumberFilter(method="filter_branch")

    def filter_branch(self, qs, name, value):
        return qs.filter(
            Q(employee__department__branch_id=value)
            | Q(employee__project__branch_id=value)
            | Q(
                employee__department__branch_id__isnull=True,
                employee__project__branch_id__isnull=True,
                employee__trade_license__branches__id=value,
            )
        )

    class Meta:
        model = RosterEntry
        fields = ["employee", "shift", "is_rest_day"]

class LeaveTypeFilter(df.FilterSet):
    code = df.CharFilter(field_name="code", lookup_expr="icontains")
    requires_doc = df.BooleanFilter()
    paid_pct_min = df.NumberFilter(field_name="paid_pct", lookup_expr="gte")
    paid_pct_max = df.NumberFilter(field_name="paid_pct", lookup_expr="lte")

    class Meta:
        model = LeaveType
        fields = ["code", "requires_doc"]
