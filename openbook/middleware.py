class ContentSecurityPolicyMiddleware:
    """Set CSP header in production (TRD §7)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        from django.conf import settings

        if not settings.DEBUG:
            response["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' https://cdn.tailwindcss.com https://cdn.jsdelivr.net https://unpkg.com 'unsafe-inline'; "
                "style-src 'self' https://cdn.tailwindcss.com 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "font-src 'self' data:;"
            )
        return response
