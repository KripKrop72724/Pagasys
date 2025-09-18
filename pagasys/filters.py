"""Reusable filter classes for API viewsets."""

import django_filters as df
from django_filters import widgets


class MultiValueCSVWidget(widgets.CSVWidget):
    """Parse both repeated query params and comma separated values."""

    def value_from_datadict(self, data, files, name):  # pragma: no cover - exercised via filters
        if hasattr(data, "getlist"):
            raw_values = data.getlist(name)
            if not raw_values:
                return []
            tokens = []
            for raw in raw_values:
                if raw in (None, ""):
                    continue
                if isinstance(raw, (list, tuple)):
                    seq = raw
                else:
                    seq = str(raw).split(",")
                tokens.extend(part.strip() for part in seq if part is not None)
            return [token for token in tokens if token]
        return super().value_from_datadict(data, files, name)


class MultiValueCSVField(df.filters.BaseCSVField):
    base_widget_class = MultiValueCSVWidget


class NumberInFilter(df.BaseInFilter, df.NumberFilter):
    """Allow filtering by multiple integer values via repeated params or CSV."""

    base_field_class = MultiValueCSVField
