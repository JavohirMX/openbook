from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.api import LoginView, LogoutView
from books.cover_views import ServeCoverView
from books.views import (
    AuthorViewSet,
    BookViewSet,
    EmbedView,
    ExportView,
    GenreViewSet,
    ImportJobDetailView,
    ImportView,
    QuoteViewSet,
    ShelfViewSet,
    StatsView,
)
from openbook.health import HealthCheckView

router = DefaultRouter()
router.register("books", BookViewSet, basename="book")
router.register("authors", AuthorViewSet, basename="author")
router.register("genres", GenreViewSet, basename="genre")
router.register("quotes", QuoteViewSet, basename="quote")
router.register("shelves", ShelfViewSet, basename="shelf")

urlpatterns = [
    path("healthz", HealthCheckView.as_view(), name="healthz"),
    path("media/covers/<path:path>", ServeCoverView.as_view(), name="serve-cover"),
    path("admin/", admin.site.urls),
    path("", include(("books.web_urls", "web"))),
    path("", include("accounts.web_urls")),
    path("api/v1/auth/login/", LoginView.as_view(), name="api-login"),
    path("api/v1/auth/logout/", LogoutView.as_view(), name="api-logout"),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/v1/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="docs",
    ),
    path("api/v1/stats/", StatsView.as_view(), name="api-stats"),
    path("api/v1/import/", ImportView.as_view(), name="api-import"),
    path("api/v1/import/jobs/<uuid:pk>/", ImportJobDetailView.as_view(), name="api-import-job-detail"),
    path("api/v1/export/", ExportView.as_view(), name="api-export"),
    path("api/v1/embed/", EmbedView.as_view(), name="api-embed"),
    path("api/v1/", include(router.urls)),
]
