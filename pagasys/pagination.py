from django.conf import settings
from rest_framework import exceptions
from rest_framework.pagination import PageNumberPagination


class AllRecordsMixin:
    """Allow list endpoints to return every record when ``all=true`` is requested."""

    all_query_param = "all"
    truthy_values = {"1", "true", "yes", "on"}
    falsy_values = {"0", "false", "no", "off"}

    def _should_return_all(self, request):
        if request is None:
            return False
        value = request.query_params.get(self.all_query_param)
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        coerced = str(value).strip().lower()
        if coerced in self.truthy_values:
            return True
        if coerced in self.falsy_values:
            return False
        raise exceptions.ValidationError(
            {self.all_query_param: [f"Invalid boolean value '{value}'"]}
        )

    def get_page_size(self, request):
        should_return_all = self._should_return_all(request)
        # ``all_requested`` is introspected by list views that perform additional slicing.
        self.all_requested = should_return_all
        if should_return_all:
            return None
        return super().get_page_size(request)


class GlobalPagination(AllRecordsMixin, PageNumberPagination):
    """Global pagination allowing clients to control page size."""

    page_size_query_param = "page_size"

    def get_page_size(self, request):
        """Return the page size from query params with an enforced maximum."""
        rf = settings.REST_FRAMEWORK
        # Allow tests or runtime to override defaults through settings.
        self.page_size = rf.get("PAGE_SIZE", self.page_size)
        self.max_page_size = rf.get("MAX_PAGE_SIZE", 1000)
        return super().get_page_size(request)
