from django import forms
from rest_framework import serializers

from pagasys.models import Branch, Department, Project
from pagasys.utils import scope_queryset

from .models import AttDay
from .views import parse_month


class MonthlyAttendanceReportForm(forms.Form):
    month = forms.CharField(
        label="Month",
        widget=forms.DateInput(attrs={"type": "month"}),
        help_text="Select the month to summarise (YYYY-MM).",
    )
    branch = forms.ModelChoiceField(
        queryset=Branch.objects.none(),
        required=False,
        empty_label="All branches",
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        empty_label="All departments",
    )
    project = forms.ModelChoiceField(
        queryset=Project.objects.none(),
        required=False,
        empty_label="All projects",
    )
    status = forms.MultipleChoiceField(
        required=False,
        choices=AttDay._meta.get_field("status").choices,
        widget=forms.SelectMultiple,
        help_text="Optional: restrict the report to specific attendance statuses.",
    )
    locked = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All days"),
            ("true", "Locked only"),
            ("false", "Unlocked only"),
        ],
        help_text="Optional: limit the report to locked or unlocked days.",
    )

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset_map = {
            "branch": Branch,
            "department": Department,
            "project": Project,
        }
        for field_name, model in queryset_map.items():
            qs = model.objects.all()
            if request is not None:
                qs = scope_queryset(qs, request.user)
            self.fields[field_name].queryset = qs.order_by("name")

    def clean_month(self):
        value = self.cleaned_data.get("month")
        try:
            parse_month(value)
        except serializers.ValidationError as exc:
            raise forms.ValidationError(exc.detail.get("month", exc.detail)) from exc
        return value

    def cleaned_statuses(self):
        return self.cleaned_data.get("status") or []

    def cleaned_locked_value(self):
        value = self.cleaned_data.get("locked")
        if value == "true":
            return True
        if value == "false":
            return False
        return None
