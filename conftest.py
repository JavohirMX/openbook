import pytest


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def user(db):
    from accounts.factories import UserFactory

    return UserFactory(email="reader@example.com", password="password123")


@pytest.fixture
def api_token(user):
    from accounts.models import ApiToken

    return ApiToken.create_for_user(user, label="Test")


@pytest.fixture
def authenticated_client(api_client, api_token):
    api_client.credentials(HTTP_AUTHORIZATION=f"Token {api_token.key}")
    return api_client
