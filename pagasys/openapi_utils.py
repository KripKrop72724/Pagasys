from typing import List
from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiParameter
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
    params = []
    for name in _get_filter_fields(viewset):
        params.append(
            OpenApiParameter(
                name,
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=f"Filter by {name}. Combine multiple parameters for compound filtering.",
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
    fields = _get_filter_fields(viewset)
    if not fields:
        return ""
    parts = [f"{name}=<value>" for name in fields[:2]]
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
