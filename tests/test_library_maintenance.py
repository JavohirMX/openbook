from unittest.mock import MagicMock, patch

from django.core.files.base import ContentFile

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse

from books.factories import BookAuthorFactory, BookFactory, BookGenreFactory
from books.import_jobs import create_metadata_backfill_job
from books.library_maintenance import (
    backfill_metadata,
    books_needing_metadata,
    clear_metadata_cache,
    enrich_book_from_metadata,
    library_health_stats,
    refresh_book_metadata,
)
from books.models import ImportJobKind, ImportJobStatus


@pytest.mark.django_db
def test_books_needing_metadata_queryset():
    complete = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/cover.jpg",
        pages=300,
        publisher="Pub",
        published_year=2020,
    )
    complete.cover_image.save(f"{complete.pk}.jpg", ContentFile(b"cover"), save=True)
    BookAuthorFactory(book=complete)
    BookGenreFactory(book=complete)

    incomplete = BookFactory(isbn_13="9780143127551", cover_url=None, pages=None)

    ids = set(books_needing_metadata().values_list("pk", flat=True))
    assert incomplete.pk in ids
    assert complete.pk not in ids


@pytest.mark.django_db
def test_library_health_stats():
    BookFactory(isbn_13="9780143127550", cover_url=None)
    BookFactory(isbn_13=None, isbn_10=None, cover_url="https://example.com/x.jpg", pages=100)

    stats = library_health_stats()
    assert stats["total_books"] == 2
    assert stats["missing_cover"] == 2
    assert stats["no_isbn"] == 1
    assert stats["needing_metadata"] >= 1


@pytest.mark.django_db
def test_enrich_book_fills_only_empty_fields():
    book = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/existing.jpg",
        pages=None,
        publisher="",
    )
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(b"cover"), save=True)
    BookAuthorFactory(book=book)

    with patch("books.library_maintenance.download_cover", return_value=True):
        result = enrich_book_from_metadata(
        book,
        {
            "cover_url": "https://example.com/new.jpg",
            "pages": 250,
            "publisher": "New Pub",
            "authors": ["Someone Else"],
            "genres": ["Fiction"],
        },
        )

    book.refresh_from_db()
    assert book.cover_url == "https://example.com/existing.jpg"
    assert book.pages == 250
    assert book.publisher == "New Pub"
    assert list(book.authors.values_list("name", flat=True)) != ["Someone Else"]
    assert "cover_url" not in result.updated_fields
    assert "pages" in result.updated_fields
    assert "authors" not in result.updated_fields


@pytest.mark.django_db
def test_enrich_book_adds_authors_when_missing():
    book = BookFactory(isbn_13="9780143127550", cover_url="https://example.com/c.jpg", pages=100)
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(b"cover"), save=True)

    with patch("books.library_maintenance.download_cover", return_value=True):
        result = enrich_book_from_metadata(book, {"authors": ["Jane Doe"]})

    assert "authors" in result.updated_fields
    assert book.authors.filter(name="Jane Doe").exists()


@pytest.mark.django_db
def test_refresh_book_metadata():
    book = BookFactory(isbn_13="9780143127550", cover_url=None, pages=None)
    mock_service = MagicMock()
    mock_service.lookup_isbn.return_value = {
        "title": book.title,
        "cover_url": "https://example.com/cover.jpg",
        "pages": 180,
    }

    with (
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=True),
    ):
        result = refresh_book_metadata(book, service=mock_service)

    book.refresh_from_db()
    assert "cover_url" in result.updated_fields
    assert book.cover_url == "https://example.com/cover.jpg"
    assert book.pages == 180


@pytest.mark.django_db
def test_backfill_metadata_progress_and_result():
    book = BookFactory(isbn_13="9780143127550", cover_url=None)
    progress_calls = []

    def progress(done, total):
        progress_calls.append((done, total))

    mock_service = MagicMock()
    mock_service.lookup_isbn.return_value = {
        "cover_url": "https://example.com/cover.jpg",
        "pages": 200,
    }

    with (
        patch("books.library_maintenance.MetadataService", return_value=mock_service),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=True),
    ):
        result = backfill_metadata([str(book.pk)], progress_callback=progress)

    book.refresh_from_db()
    assert result.updated == 1
    assert book.cover_url == "https://example.com/cover.jpg"
    assert progress_calls[-1] == (1, 1)


@pytest.mark.django_db
def test_backfill_reports_lookup_failure_distinctly():
    book = BookFactory(isbn_13="9780143127550", cover_url=None)
    mock_service = MagicMock()
    mock_service.lookup_isbn.side_effect = RuntimeError("network down")

    with (
        patch("books.library_maintenance.MetadataService", return_value=mock_service),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
    ):
        result = backfill_metadata([str(book.pk)])

    assert result.updated == 0
    assert any("metadata lookup failed" in err for err in result.errors)
    assert not any("no metadata found for ISBN" in err for err in result.errors)


@pytest.mark.django_db
def test_backfill_reports_empty_api_response():
    book = BookFactory(isbn_13="9780143127550", cover_url=None)
    mock_service = MagicMock()
    mock_service.lookup_isbn.return_value = {}

    with (
        patch("books.library_maintenance.MetadataService", return_value=mock_service),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
    ):
        result = backfill_metadata([str(book.pk)])

    assert result.updated == 0
    assert any("no metadata found for ISBN" in err for err in result.errors)


@pytest.mark.django_db
def test_clear_metadata_cache_locmem(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    cache.set("metadata:isbn:9780143127550", {"title": "Cached"}, 3600)
    clear_metadata_cache()
    assert cache.get("metadata:isbn:9780143127550") is None


@pytest.mark.django_db
def test_process_metadata_backfill_job(user):
    book = BookFactory(isbn_13="9780143127550", cover_url=None)
    job = create_metadata_backfill_job(user, [str(book.pk)])

    with (
        patch("books.library_maintenance.MetadataService") as mock_cls,
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=True),
    ):
        mock_cls.return_value.lookup_isbn.return_value = {
            "cover_url": "https://example.com/job-cover.jpg",
            "pages": 120,
        }
        call_command("process_import_jobs")

    job.refresh_from_db()
    assert job.kind == ImportJobKind.METADATA_BACKFILL
    assert job.status == ImportJobStatus.COMPLETED
    assert job.result["updated"] == 1

    book.refresh_from_db()
    assert book.cover_url == "https://example.com/job-cover.jpg"


@pytest.fixture
def web_user(db):
    from accounts.factories import UserFactory

    return UserFactory(email="tools@example.com", password="password123")


@pytest.fixture
def logged_in_client(client, web_user):
    client.login(username="tools@example.com", password="password123")
    return client


@pytest.mark.django_db
def test_library_tools_page_loads(logged_in_client):
    BookFactory(isbn_13="9780143127550", cover_url=None)
    response = logged_in_client.get(reverse("web:library-tools"))
    assert response.status_code == 200
    assert b"Library Tools" in response.content
    assert b"Library health" in response.content
    assert b"Need metadata" in response.content


@pytest.mark.django_db
def test_library_tools_backfill_queues_job(logged_in_client, web_user):
    book = BookFactory(isbn_13="9780143127550", cover_url=None)
    response = logged_in_client.post(
        reverse("web:library-tools"),
        {"action": "backfill_metadata"},
    )
    assert response.status_code == 302
    job = web_user.import_jobs.get()
    assert job.kind == ImportJobKind.METADATA_BACKFILL
    assert str(book.pk) in job.book_ids


@pytest.mark.django_db
def test_library_tools_clear_cache(logged_in_client, settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    cache.set("metadata:isbn:9780143127550", {"title": "X"}, 3600)
    response = logged_in_client.post(
        reverse("web:library-tools"),
        {"action": "clear_metadata_cache"},
    )
    assert response.status_code == 302
    assert cache.get("metadata:isbn:9780143127550") is None


@pytest.mark.django_db
def test_book_refresh_metadata_view(logged_in_client):
    from books.library_maintenance import EnrichResult

    book = BookFactory(isbn_13="9780143127550", cover_url=None)

    with patch(
        "books.web_views.refresh_book_metadata",
        return_value=EnrichResult(updated_fields=["cover_url", "pages"]),
    ):
        response = logged_in_client.post(reverse("web:book-refresh-metadata", kwargs={"pk": book.pk}))

    assert response.status_code == 302
    assert response.url == reverse("web:book-detail", kwargs={"pk": book.pk})


@pytest.mark.django_db
def test_book_detail_shows_refresh_button(logged_in_client):
    book = BookFactory(isbn_13="9780143127550")
    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    assert b"Refresh metadata" in response.content


@pytest.mark.django_db
def test_book_detail_hides_refresh_without_isbn(logged_in_client):
    book = BookFactory(isbn_13=None, isbn_10=None)
    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    assert b"Refresh metadata" not in response.content
