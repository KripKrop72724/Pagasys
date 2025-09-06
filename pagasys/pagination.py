from django.conf import settings
from rest_framework.pagination import PageNumberPagination


class GlobalPagination(PageNumberPagination):
    """Global pagination allowing clients to control page size."""

    page_size_query_param = "page_size"

    def get_page_size(self, request):
        """Return the page size from query params with an enforced maximum."""
        rf = settings.REST_FRAMEWORK
        # Allow tests or runtime to override defaults through settings.
        self.page_size = rf.get("PAGE_SIZE", self.page_size)
        self.max_page_size = rf.get("MAX_PAGE_SIZE", 1000)
        return super().get_page_size(request)
