import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_empty_db_root_redirects_to_setup(client):
    response = client.get(reverse("web:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("setup")


@pytest.mark.django_db
def test_empty_db_login_redirects_to_setup(client):
    response = client.get(reverse("login"))
    assert response.status_code == 302
    assert response.url == reverse("setup")


@pytest.mark.django_db
def test_setup_page_loads_when_no_users(client):
    response = client.get(reverse("setup"))
    assert response.status_code == 200
    assert b"Welcome to openbook" in response.content


@pytest.mark.django_db
def test_setup_creates_superuser_and_logs_in(client):
    response = client.post(
        reverse("setup"),
        {
            "email": "operator@example.com",
            "password1": "secure-pass-123",
            "password2": "secure-pass-123",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("web:dashboard")

    user = User.objects.get(email="operator@example.com")
    assert user.is_superuser is True
    assert user.is_staff is True

    dashboard = client.get(reverse("web:dashboard"))
    assert dashboard.status_code == 200


@pytest.mark.django_db
def test_setup_rejected_when_user_already_exists(client):
    User.objects.create_superuser(email="existing@example.com", password="password123")

    response = client.get(reverse("setup"))
    assert response.status_code == 302
    assert response.url == reverse("login")


@pytest.mark.django_db
def test_second_setup_post_rejected(client):
    client.post(
        reverse("setup"),
        {
            "email": "first@example.com",
            "password1": "secure-pass-123",
            "password2": "secure-pass-123",
        },
    )
    client.logout()

    response = client.post(
        reverse("setup"),
        {
            "email": "second@example.com",
            "password1": "secure-pass-456",
            "password2": "secure-pass-456",
        },
    )
    assert response.status_code == 302
    assert response.url == reverse("login")
    assert User.objects.count() == 1
    assert User.objects.filter(email="second@example.com").exists() is False


@pytest.mark.django_db
def test_login_page_loads_after_setup(client):
    User.objects.create_user(email="reader@example.com", password="password123")
    response = client.get(reverse("login"))
    assert response.status_code == 200
