from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from accounts.models import ApiToken


class ApiTokenAuthentication(BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != self.keyword.lower().encode():
            return None

        if len(auth) == 1:
            raise exceptions.AuthenticationFailed("Invalid token header. No credentials provided.")
        if len(auth) > 2:
            raise exceptions.AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        try:
            token_key = auth[1].decode()
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed(
                "Invalid token header. Token string should not contain invalid characters."
            ) from exc

        return self.authenticate_credentials(token_key)

    def authenticate_credentials(self, key):
        try:
            token = ApiToken.objects.select_related("user").get(key=key)
        except ApiToken.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("Invalid token.") from exc

        if not token.user.is_active:
            raise exceptions.AuthenticationFailed("User inactive or deleted.")

        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return (token.user, token)

    def authenticate_header(self, request):
        return self.keyword
