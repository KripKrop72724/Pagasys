from rest_framework.filters import BaseFilterBackend
from pagasys.utils import scope_queryset

class ScopeFilterBackend(BaseFilterBackend):
    """Apply role-based scoping to querysets."""

    def filter_queryset(self, request, queryset, view):
        return scope_queryset(queryset, request.user)
