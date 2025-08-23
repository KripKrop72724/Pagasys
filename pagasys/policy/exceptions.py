from rest_framework.views import exception_handler


def unified_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response
    data = response.data
    if isinstance(data, dict):
        detail = data.get("detail")
        errors = {k: v for k, v in data.items() if k != "detail"}
        response.data = {"detail": detail or "Validation error", "errors": errors}
    else:
        response.data = {"detail": "Error", "errors": data}
    return response
