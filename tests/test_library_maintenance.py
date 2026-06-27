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
    book_needs_metadata,
    books_needing_metadata,
    clear_metadata_cache,
    enrich_book_from_metadata,
    library_health_stats,
    metadata_missing_fields,
    refresh_book_metadata,
)
from books.metadata_match import LookupResult
from books.models import ImportJobKind, ImportJobStatus

VALID_COVER_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
OL_PLACEHOLDER_GIF = b"GIF89a" + b"\x01\x00\x01\x00" + b"\x00" * 800


@pytest.mark.django_db
def test_books_needing_metadata_queryset():
    complete = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/cover.jpg",
        pages=300,
        publisher="Pub",
        published_year=2020,
        description="A complete bibliographic record for testing.",
    )
    complete.cover_image.save(f"{complete.pk}.jpg", ContentFile(VALID_COVER_JPEG), save=True)
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
    assert stats["missing_cover"] == 1
    assert stats["no_isbn"] == 1
    assert stats["needing_metadata"] >= 1


@pytest.mark.django_db
def test_library_health_stats_counts_placeholder_cover_as_missing(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    BookFactory(cover_url="https://example.com/x.jpg", pages=100)
    invalid = BookFactory(cover_url=None)
    invalid.cover_image.save(f"{invalid.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    stats = library_health_stats()
    assert stats["missing_cover"] == 1


@pytest.mark.django_db
def test_enrich_book_fills_only_empty_fields():
    book = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/existing.jpg",
        pages=None,
        publisher="",
    )
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(VALID_COVER_JPEG), save=True)
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
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(VALID_COVER_JPEG), save=True)

    with patch("books.library_maintenance.download_cover", return_value=True):
        result = enrich_book_from_metadata(book, {"authors": ["Jane Doe"]})

    assert "authors" in result.updated_fields
    assert book.authors.filter(name="Jane Doe").exists()


@pytest.mark.django_db
def test_refresh_book_metadata_uses_interactive_chain():
    book = BookFactory(isbn_13="9780143127550")
    with (
        patch("books.library_maintenance.lookup_for_book") as mock_lookup,
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
    ):
        mock_lookup.return_value = LookupResult(metadata={}, score=0.0)
        refresh_book_metadata(book)
    mock_lookup.assert_called_once_with(book, import_context=False)


@pytest.mark.django_db
def test_book_complete_without_subtitle_or_series():
    book = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/cover.jpg",
        pages=300,
        publisher="Pub",
        published_year=2020,
        description="Complete without optional fields.",
        subtitle=None,
    )
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(VALID_COVER_JPEG), save=True)
    BookAuthorFactory(book=book)
    BookGenreFactory(book=book)

    assert book_needs_metadata(book) is False
    assert metadata_missing_fields(book) == []


@pytest.mark.django_db
def test_metadata_missing_fields_excludes_subtitle_and_series():
    book = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/cover.jpg",
        pages=300,
        publisher="Pub",
        published_year=2020,
        description="Only optional fields missing.",
        subtitle=None,
    )
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(VALID_COVER_JPEG), save=True)
    BookAuthorFactory(book=book)
    BookGenreFactory(book=book)

    missing = metadata_missing_fields(book)
    assert "subtitle" not in missing
    assert "series" not in missing


@pytest.mark.django_db
def test_book_needs_metadata_when_description_missing():
    book = BookFactory(
        isbn_13="9780143127550",
        cover_url="https://example.com/c.jpg",
        pages=100,
        publisher="Ace",
        published_year=1965,
        description=None,
    )
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(VALID_COVER_JPEG), save=True)
    from books.models import GenreSource
    from books.services import add_authors_to_book, add_genres_to_book

    add_authors_to_book(book, ["Author"])
    add_genres_to_book(book, ["Fiction"], source=GenreSource.OPEN_LIBRARY)
    from books.library_maintenance import book_needs_metadata

    assert book_needs_metadata(book) is True


@pytest.mark.django_db
def test_refresh_book_metadata():
    book = BookFactory(isbn_13="9780143127550", cover_url=None, pages=None)
    lookup = LookupResult(
        metadata={
            "title": book.title,
            "cover_url": "https://example.com/cover.jpg",
            "pages": 180,
        },
        score=0.95,
        auto_apply=True,
    )

    with (
        patch("books.library_maintenance.lookup_for_book", return_value=lookup),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=True),
    ):
        result = refresh_book_metadata(book)

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

    lookup = LookupResult(
        metadata={
            "cover_url": "https://example.com/cover.jpg",
            "pages": 200,
        },
        score=0.95,
        auto_apply=True,
    )

    with (
        patch("books.library_maintenance.lookup_for_book", return_value=lookup),
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

    with (
        patch("books.library_maintenance.lookup_for_book", side_effect=RuntimeError("network down")),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
    ):
        result = backfill_metadata([str(book.pk)])

    assert result.updated == 0
    assert result.failed == 1
    assert any("metadata lookup failed" in err for err in result.errors)


@pytest.mark.django_db
def test_backfill_reports_empty_api_response():
    book = BookFactory(isbn_13="9780143127550", cover_url=None)

    with (
        patch("books.library_maintenance.lookup_for_book", return_value=LookupResult()),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
    ):
        result = backfill_metadata([str(book.pk)])

    assert result.updated == 0
    assert any("no metadata found" in err for err in result.errors)


@pytest.mark.django_db
def test_backfill_queues_pending_review():
    book = BookFactory(title="Dune", isbn_13=None, isbn_10=None, cover_url=None)
    BookAuthorFactory(book=book, author__name="Frank Herbert")
    lookup = LookupResult(
        metadata={"title": "Dune", "authors": ["Frank Herbert"], "isbn_13": "9780441172719"},
        score=0.75,
        auto_apply=False,
        needs_review=True,
    )

    with (
        patch("books.library_maintenance.lookup_for_book", return_value=lookup),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
    ):
        result = backfill_metadata([str(book.pk)])

    assert result.pending_review == 1
    assert book.metadata_proposals.filter(status="pending").exists()


@pytest.mark.django_db
def test_backfill_metadata_respects_should_stop():
    books = [BookFactory(isbn_13=f"978014312756{i}", cover_url=None) for i in range(3)]
    lookup = LookupResult(
        metadata={"pages": 120},
        score=0.95,
        auto_apply=True,
    )
    calls = {"n": 0}

    def lookup_side_effect(book, import_context=False):
        calls["n"] += 1
        return lookup

    def should_stop():
        return calls["n"] >= 1

    with (
        patch("books.library_maintenance.lookup_for_book", side_effect=lookup_side_effect),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=False),
        patch("books.library_maintenance.book_needs_metadata", return_value=True),
    ):
        result = backfill_metadata(
            [str(b.pk) for b in books],
            should_stop=should_stop,
        )

    assert calls["n"] == 1
    assert result.updated == 1


@pytest.mark.django_db
def test_backfill_metadata_stops_before_lookup():
    books = [BookFactory(isbn_13=f"978014312756{i}", cover_url=None) for i in range(3)]
    calls = {"n": 0}

    def lookup_side_effect(book, import_context=False):
        calls["n"] += 1
        return LookupResult(metadata={"pages": 120}, score=0.95, auto_apply=True)

    with (
        patch("books.library_maintenance.lookup_for_book", side_effect=lookup_side_effect),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=False),
        patch("books.library_maintenance.book_needs_metadata", return_value=True),
    ):
        result = backfill_metadata(
            [str(b.pk) for b in books],
            should_stop=lambda: True,
        )

    assert calls["n"] == 0
    assert result.updated == 0


@pytest.mark.django_db
def test_process_metadata_backfill_job(user):
    book = BookFactory(isbn_13="9780143127550", cover_url=None)
    job = create_metadata_backfill_job(user, [str(book.pk)])
    lookup = LookupResult(
        metadata={
            "cover_url": "https://example.com/job-cover.jpg",
            "pages": 120,
        },
        score=0.95,
        auto_apply=True,
    )

    with (
        patch("books.library_maintenance.lookup_for_book", return_value=lookup),
        patch("books.library_maintenance.openlibrary_import_delay_seconds", return_value=0),
        patch("books.library_maintenance.download_cover", return_value=True),
    ):
        call_command("process_import_jobs")

    job.refresh_from_db()
    assert job.kind == ImportJobKind.METADATA_BACKFILL
    assert job.status == ImportJobStatus.COMPLETED
    assert job.result["updated"] == 1

    book.refresh_from_db()
    assert book.cover_url == "https://example.com/job-cover.jpg"


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
def test_metadata_match_apply(logged_in_client):
    from books.factories import MetadataMatchProposalFactory

    proposal = MetadataMatchProposalFactory(
        candidate={
            "cover_url": "https://example.com/proposed.jpg",
            "pages": 333,
            "isbn_13": "9780143127741",
        }
    )
    response = logged_in_client.post(
        reverse("web:metadata-match-apply", kwargs={"pk": proposal.pk}),
    )
    assert response.status_code == 302
    proposal.refresh_from_db()
    assert proposal.status == "applied"
    proposal.book.refresh_from_db()
    assert proposal.book.pages == 333


@pytest.mark.django_db
def test_library_tools_shows_pending_matches(logged_in_client):
    from books.factories import MetadataMatchProposalFactory

    MetadataMatchProposalFactory()
    response = logged_in_client.get(reverse("web:library-tools"))
    assert b"Pending matches" in response.content


@pytest.mark.django_db
def test_book_detail_shows_refresh_without_isbn(logged_in_client):
    book = BookFactory(isbn_13=None, isbn_10=None, title="Sparse Manual Entry")
    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    assert b"Refresh metadata" in response.content


@pytest.mark.django_db
def test_book_refresh_metadata_title_only_book(logged_in_client):
    from books.library_maintenance import EnrichResult

    book = BookFactory(isbn_13=None, isbn_10=None, title="Title Only Book")

    with patch(
        "books.web_views.refresh_book_metadata",
        return_value=EnrichResult(updated_fields=["pages"]),
    ):
        response = logged_in_client.post(reverse("web:book-refresh-metadata", kwargs={"pk": book.pk}))

    assert response.status_code == 302
    assert response.url == reverse("web:book-detail", kwargs={"pk": book.pk})
