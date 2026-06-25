from django.contrib.auth import get_user_model
from django.shortcuts import redirect

User = get_user_model()

SETUP_PATH = "/setup/"
ALLOWED_WITHOUT_USERS = (
    SETUP_PATH,
    "/healthz",
    "/static/",
    "/admin/login/",
    "/api/",
)


class FirstRunSetupMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if User.objects.exists():
            if request.path == SETUP_PATH:
                return redirect("login")
            return self.get_response(request)

        if self._is_allowed_without_users(request.path):
            return self.get_response(request)

        return redirect("setup")

    def _is_allowed_without_users(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in ALLOWED_WITHOUT_USERS)
