from django.conf import settings


def app_version(request):
    return {
        "app_version": "0.1.0",
        "github_repo_url": settings.GITHUB_REPO_URL,
    }
