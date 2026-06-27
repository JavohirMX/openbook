import pytest
from django.urls import reverse
from rest_framework import status

from accounts.models import ApiToken


@pytest.fixture
def user(db):
    from accounts.factories import UserFactory

    return UserFactory(email="reader@example.com", password="password123")


@pytest.mark.django_db
def test_login_success_returns_token_in_envelope(api_client, user):
    response = api_client.post(
        reverse("api-login"),
        {"email": "reader@example.com", "password": "password123"},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"data": {"token": response.json()["data"]["token"]}}
    assert len(response.json()["data"]["token"]) > 0
    assert ApiToken.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_login_invalid_credentials_returns_401(api_client, user):
    response = api_client.post(
        reverse("api-login"),
        {"email": "reader@example.com", "password": "wrong-password"},
        format="json",
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    body = response.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["message"] == "Invalid email or password."
    assert body["error"]["details"] is None


@pytest.mark.django_db
def test_authenticated_request_with_token_header(api_client, user):
    token = ApiToken.create_for_user(user, label="Test")
    api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = api_client.post(reverse("api-logout"))

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"data": None}
    assert not ApiToken.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
def test_auth_throttle_returns_429(settings, api_client, user, monkeypatch):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    monkeypatch.setattr(
        "openbook.api.throttling.AuthRateThrottle.get_rate",
        lambda self: "1/min",
    )

    payload = {"email": "reader@example.com", "password": "password123"}

    first = api_client.post(reverse("api-login"), payload, format="json")
    assert first.status_code == status.HTTP_200_OK

    second = api_client.post(reverse("api-login"), payload, format="json")
    assert second.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    body = second.json()
    assert body["error"]["code"] == "throttled"
    assert "Retry-After" in second
