from rest_framework.authentication import BaseAuthentication
from rest_framework import exceptions

from .models import AttendanceDevice


class DeviceKeyAuthentication(BaseAuthentication):
    """Authenticate capture devices via an API key.

    The device is looked up using the ``X-Device-Key`` header. On success the
    request is annotated with ``device`` and ``company`` attributes while no
    user principal is returned. Missing headers simply result in no
    authentication attempt.
    """

    keyword = "X-Device-Key"

    def authenticate(self, request):
        key = request.headers.get(self.keyword)
        if not key:
            return None
        try:
            device = AttendanceDevice.objects.select_related("company").get(
                api_key=key, is_active=True
            )
        except AttendanceDevice.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("Invalid device key") from exc

        request.device = device
        request.company = device.company
        # device-based endpoint: no user principal
        return (None, None)
