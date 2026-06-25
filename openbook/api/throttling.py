from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle as DRFUserRateThrottle


class UserRateThrottle(DRFUserRateThrottle):
    """Per-token rate limit for authenticated API requests."""

    scope = "user"


class AuthRateThrottle(SimpleRateThrottle):
    """Rate limit for unauthenticated auth endpoints (login)."""

    scope = "auth"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
