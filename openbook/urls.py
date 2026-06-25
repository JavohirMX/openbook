from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.api import LoginView, LogoutView

router = DefaultRouter()
# Future viewsets register here, e.g. router.register("books", BookViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/auth/login/", LoginView.as_view(), name="api-login"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="api-logout"),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="docs",
    ),
    path("api/v1/", include(router.urls)),
]
