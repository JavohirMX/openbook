from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from accounts.api import LoginView, LogoutView
from books.cover_views import ServeCoverView
from books.opds import opds_catalog_response
from books.views import (
    AuthorViewSet,
    BookViewSet,
    EmbedView,
    ExportView,
    GenreViewSet,
    ImportBackfillView,
    ImportJobDetailView,
    ImportView,
    QuoteViewSet,
    ReadingGoalViewSet,
    SeriesViewSet,
    ShelfViewSet,
    StatsView,
    WebhookEndpointViewSet,
)
from openbook.health import HealthCheckView

router = DefaultRouter()
router.register("books", BookViewSet, basename="book")
router.register("authors", AuthorViewSet, basename="author")
router.register("genres", GenreViewSet, basename="genre")
router.register("series", SeriesViewSet, basename="series")
router.register("quotes", QuoteViewSet, basename="quote")
router.register("shelves", ShelfViewSet, basename="shelf")
router.register("reading-goals", ReadingGoalViewSet, basename="reading-goal")
router.register("webhooks", WebhookEndpointViewSet, basename="webhook")

urlpatterns = [
    path("healthz", HealthCheckView.as_view(), name="healthz"),
    path("opds/", opds_catalog_response, name="opds-catalog"),
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
    path("api/v1/import/backfill/", ImportBackfillView.as_view(), name="api-import-backfill"),
    path("api/v1/import/jobs/<uuid:pk>/", ImportJobDetailView.as_view(), name="api-import-job-detail"),
    path("api/v1/export/", ExportView.as_view(), name="api-export"),
    path("api/v1/embed/", EmbedView.as_view(), name="api-embed"),
    path("api/v1/", include(router.urls)),
]
