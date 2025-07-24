from typing import List
from drf_spectacular.utils import extend_schema_view, extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes


def _get_filter_fields(viewset) -> List[str]:
    """Return filter field names for a viewset."""
    fields = []
    if getattr(viewset, "filterset_fields", None):
        fs = viewset.filterset_fields
        if isinstance(fs, dict):
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


def document_filters(viewset):
    """Attach dynamic filter documentation to a viewset's list action."""
    params = _generate_parameters(viewset)
    return extend_schema_view(list=extend_schema(parameters=params))(viewset)
