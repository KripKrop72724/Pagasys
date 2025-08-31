from typing import List
import django_filters as df
from drf_spectacular.utils import (
    extend_schema_view,
    extend_schema,
    OpenApiParameter,
    OpenApiExample,
)
from drf_spectacular.types import OpenApiTypes


def _get_filter_fields(viewset) -> List[str]:
    """Return filter field names for a viewset."""
    fields = []
    if getattr(viewset, "filterset_fields", None) is not None:
        fs = viewset.filterset_fields
        if fs == "__all__":
            model = getattr(viewset, "queryset", None)
            if model is not None:
                model = model.model
            else:
                model = viewset.serializer_class.Meta.model
            fields = [
                f.name
                for f in model._meta.get_fields()
                if (getattr(f, "concrete", False) or f.many_to_many)
                and not f.auto_created
            ]
        elif isinstance(fs, dict):
            fields = list(fs.keys())
        else:
            fields = list(fs)
    elif getattr(viewset, "filterset_class", None):
        filters = viewset.filterset_class().filters
        fields = list(filters.keys())
    return list(fields)


def _generate_parameters(viewset) -> List[OpenApiParameter]:
    """Build OpenAPI parameters including examples for booleans."""
    params: List[OpenApiParameter] = []
    filters = {}
    if getattr(viewset, "filterset_class", None):
        filters = viewset.filterset_class().filters
    for name in _get_filter_fields(viewset):
        filt = filters.get(name)
        is_bool = isinstance(filt, df.BooleanFilter)
        is_choice = isinstance(filt, df.ChoiceFilter)
        example = "true" if is_bool else "<value>"
        enum = None
        if is_choice:
            choices = [c[0] for c in filt.extra.get("choices", [])]
            enum = choices if choices else None
            if choices:
                example = choices[0]
        desc = f"Filter by {name}. Combine multiple parameters for compound filtering."
        if name == "nationality":
            desc = (
                "Filter by nationality using ISO 3166-1 alpha-2 country codes. "
                "Combine multiple parameters for compound filtering."
            )
        params.append(
            OpenApiParameter(
                name,
                OpenApiTypes.BOOL if is_bool else OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=desc,
                examples=[OpenApiExample("Example", value=example)],
                enum=enum,
            )
        )
    params.append(
        OpenApiParameter(
            "ordering",
            OpenApiTypes.STR,
            OpenApiParameter.QUERY,
            description="Comma-separated list of fields to sort by",
        )
    )
    return params


def _build_example_query(viewset) -> str:
    """Return a generic example query string for compounding filters."""
    filters = {}
    if getattr(viewset, "filterset_class", None):
        filters = viewset.filterset_class().filters
        fields = list(filters.keys())
    else:
        fields = _get_filter_fields(viewset)
    if not fields:
        return ""
    parts = []
    for name in fields[:2]:
        filt = filters.get(name)
        val = "true" if isinstance(filt, df.BooleanFilter) else "<value>"
        parts.append(f"{name}={val}")
    return "?" + "&".join(parts)


def document_filters(viewset):
    """Attach dynamic filter documentation to a viewset's list action."""
    params = _generate_parameters(viewset)
    example = _build_example_query(viewset)
    description = (
        "Compound filtering is supported."
        + (f" Example: {example}" if example else "")
    )
    return extend_schema_view(
        list=extend_schema(parameters=params, description=description)
    )(viewset)
