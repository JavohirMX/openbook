from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone


class UserTimezoneMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tzname = "UTC"
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            profile = getattr(user, "profile", None)
            if profile and profile.timezone:
                tzname = profile.timezone
        try:
            timezone.activate(ZoneInfo(tzname))
        except ZoneInfoNotFoundError:
            timezone.deactivate()
        response = self.get_response(request)
        timezone.deactivate()
        return response
