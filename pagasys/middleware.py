from django.utils import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CompanyTimezoneMiddleware:
    """Activate the authenticated user's company timezone for each request.

    Falls back to the default timezone when the user is anonymous or the
    company timezone is invalid or missing. The timezone is deactivated after
    the response to avoid leaking state between requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tz = None
        if getattr(request, "user", None) and request.user.is_authenticated:
            company = getattr(request.user, "company", None)
            tz = getattr(company, "timezone", None)
        try:
            if tz:
                timezone.activate(ZoneInfo(tz))
            else:
                timezone.deactivate()
        except ZoneInfoNotFoundError:
            timezone.deactivate()
        try:
            response = self.get_response(request)
        finally:
            timezone.deactivate()
        return response
