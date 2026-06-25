from django.conf import settings
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework.views import exception_handler

ERROR_CODES = {
    400: "validation_error",
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    409: "duplicate_isbn",
    413: "payload_too_large",
    422: "unprocessable",
    429: "throttled",
    500: "server_error",
}


def _extract_message(response_data):
    if isinstance(response_data, dict):
        if "detail" in response_data:
            detail = response_data["detail"]
            if isinstance(detail, list):
                return "; ".join(str(item) for item in detail)
            return str(detail)
        if len(response_data) == 1:
            value = next(iter(response_data.values()))
            if isinstance(value, list) and value:
                return str(value[0])
    if isinstance(response_data, list) and response_data:
        return str(response_data[0])
    return "Request failed."


def _extract_details(response_data, status_code):
    if status_code == 400 and isinstance(response_data, dict) and "detail" not in response_data:
        return response_data
    return None


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is None:
        return Response(
            {
                "error": {
                    "code": "server_error",
                    "message": "An unexpected error occurred.",
                    "details": None if not settings.DEBUG else str(exc),
                }
            },
            status=500,
        )

    status_code = response.status_code
    code = ERROR_CODES.get(status_code, "server_error")
    message = _extract_message(response.data)
    details = _extract_details(response.data, status_code)

    if status_code == 401 and message == "Request failed.":
        message = "Authentication credentials were not provided."

    response.data = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
        }
    }

    if isinstance(exc, Throttled):
        wait = int(exc.wait) if exc.wait is not None else 60
        response["Retry-After"] = str(wait)

    return response
