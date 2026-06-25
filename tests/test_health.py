import django


def test_django_setup():
    django.setup()
    from django.conf import settings

    assert settings.INSTALLED_APPS
    assert settings.AUTH_USER_MODEL == "accounts.User"
