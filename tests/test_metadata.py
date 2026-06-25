import csv
import io
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.cache import cache
from django.db import OperationalError

from books.import_export import import_goodreads_csv, import_isbns
from books.metadata import MetadataService, metadata_user_agent, openlibrary_import_delay_seconds
from books.models import Book

VALID_ISBN_13 = "9780306406157"


def _mock_response(json_data, status_code=200, headers=None):
    mock = MagicMock()
    mock.status_code = status_code
    mock.headers = headers or {}
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        from requests import HTTPError

        mock.raise_for_status.side_effect = HTTPError(response=mock)
    return mock


@pytest.fixture
def locmem_cache(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_metadata_user_agent_with_contact_email(settings):
    settings.OPENLIBRARY_CONTACT_EMAIL = "operator@example.com"
    settings.APP_VERSION = "0.1.0"
    assert metadata_user_agent() == "openbook/0.1.0 (operator@example.com)"


@pytest.mark.django_db
def test_metadata_user_agent_without_contact_email(settings):
    settings.OPENLIBRARY_CONTACT_EMAIL = ""
    settings.ALLOWED_HOSTS = ["books.javohirmx.com"]
    assert metadata_user_agent() == "openbook/0.1.0 (+https://books.javohirmx.com)"


@pytest.mark.django_db
def test_openlibrary_import_delay_auto_with_email(settings):
    settings.METADATA_IMPORT_DELAY_SECONDS = 0
    settings.OPENLIBRARY_CONTACT_EMAIL = "operator@example.com"
    assert openlibrary_import_delay_seconds() == 0.35


@pytest.mark.django_db
def test_openlibrary_import_delay_auto_without_email(settings):
    settings.METADATA_IMPORT_DELAY_SECONDS = 0
    settings.OPENLIBRARY_CONTACT_EMAIL = ""
    assert openlibrary_import_delay_seconds() == 1.0


@pytest.mark.django_db
def test_metadata_service_sends_identified_user_agent(settings):
    settings.OPENLIBRARY_CONTACT_EMAIL = "operator@example.com"
    service = MetadataService()
    assert service.session.headers["User-Agent"] == "openbook/0.1.0 (operator@example.com)"


@pytest.mark.django_db
def test_metadata_retry_sleeps_on_failure(locmem_cache):
    service = MetadataService()
    with patch.object(service.session, "get", side_effect=requests.exceptions.ConnectionError("timeout")):
        with patch("books.metadata.time.sleep") as mock_sleep:
            result = service._get("https://openlibrary.org/api/books")

    assert result is None
    assert mock_sleep.call_count == 1


@pytest.mark.django_db
def test_metadata_429_honors_retry_after(locmem_cache):
    service = MetadataService()
    rate_limited = _mock_response({}, status_code=429, headers={"Retry-After": "3"})
    success = _mock_response({"items": []})

    with patch.object(service.session, "get", side_effect=[rate_limited, success]):
        with patch("books.metadata.time.sleep") as mock_sleep:
            response = service._get("https://www.googleapis.com/books/v1/volumes")

    assert response is success
    mock_sleep.assert_called_once_with(3)


@pytest.mark.django_db
def test_transient_failure_not_cached(locmem_cache):
    service = MetadataService()
    with patch.object(service, "_lookup_open_library", return_value=None):
        with patch.object(service, "_lookup_google_books", return_value=None):
            result = service.lookup_isbn(VALID_ISBN_13)

    assert result == {}
    assert cache.get(f"metadata:isbn:{VALID_ISBN_13}") is None


@pytest.mark.django_db
def test_success_cached(locmem_cache):
    service = MetadataService()
    metadata = {"title": "Cached Book", "authors": ["Author"]}
    with patch.object(service, "_lookup_open_library", return_value=metadata):
        result = service.lookup_isbn(VALID_ISBN_13)

    assert result["title"] == "Cached Book"
    assert cache.get(f"metadata:isbn:{VALID_ISBN_13}") == metadata


@pytest.mark.django_db
def test_empty_miss_uses_negative_cache(locmem_cache):
    service = MetadataService()
    with patch.object(service, "_lookup_open_library", return_value={}):
        with patch.object(service, "_lookup_google_books", return_value={}):
            result = service.lookup_isbn(VALID_ISBN_13)

    assert result == {}
    cached = cache.get(f"metadata:isbn:{VALID_ISBN_13}")
    assert cached == {}


@pytest.mark.django_db
def test_lookup_isbn_falls_back_when_cache_unavailable(locmem_cache):
    service = MetadataService()
    metadata = {"title": "Uncached Book", "authors": ["Author"]}
    with patch(
        "books.metadata.cache.get",
        side_effect=OperationalError("no such table: openbook_cache"),
    ):
        with patch("books.metadata.cache.set"):
            with patch.object(service, "_lookup_open_library", return_value=metadata):
                result = service.lookup_isbn(VALID_ISBN_13)

    assert result["title"] == "Uncached Book"


@pytest.mark.django_db
def test_search_books_falls_back_when_cache_unavailable(locmem_cache):
    service = MetadataService()
    results = [{"title": "Search Hit", "authors": ["Author"]}]
    with patch(
        "books.metadata.cache.get",
        side_effect=OperationalError("no such table: openbook_cache"),
    ):
        with patch("books.metadata.cache.set"):
            with patch.object(service, "_search_open_library", return_value=results):
                result = service.search_books("test query")

    assert result[0]["title"] == "Search Hit"


@pytest.mark.django_db
def test_open_library_lookup_normalizes_genres(locmem_cache):
    service = MetadataService()
    ol_payload = {
        f"ISBN:{VALID_ISBN_13}": {
            "title": "Test Book",
            "authors": [{"name": "Author"}],
            "subjects": [
                {"name": "Fiction, thrillers"},
                {"name": "nyt:tag"},
                {"name": "heiresses"},
                {"name": "Crime"},
            ],
        }
    }
    with patch.object(service.session, "get") as mock_get:
        mock_get.return_value = _mock_response(ol_payload)
        result = service.lookup_isbn(VALID_ISBN_13)

    assert result["title"] == "Test Book"
    assert "Thriller" in result["genres"]
    assert "Crime" in result["genres"]
    assert "heiresses" not in result["genres"]
    assert len(result["genres"]) <= 3


@pytest.mark.django_db
def test_goodreads_import_without_enrichment(settings):
    settings.IMPORT_GOODREADS_ENRICH_METADATA = False
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "CSV Only Book", "CSV Author", "", f'="{VALID_ISBN_13}"', "0", "",
        "250", "2021", "CSV Pub", "read", "",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "goodreads.csv"

    with patch.object(MetadataService, "lookup_isbn") as mock_lookup:
        result = import_goodreads_csv(file)

    assert result.added == 1
    mock_lookup.assert_not_called()
    book = Book.objects.get(title="CSV Only Book")
    assert book.publisher == "CSV Pub"


@pytest.mark.django_db
def test_goodreads_import_succeeds_when_enrichment_fails(settings):
    settings.IMPORT_GOODREADS_ENRICH_METADATA = True
    settings.METADATA_IMPORT_DELAY_SECONDS = 0
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "Enriched Fail Book", "Author", "", f'="{VALID_ISBN_13}"', "0", "",
        "100", "2020", "Pub", "to-read", "",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "goodreads.csv"

    with patch.object(
        MetadataService,
        "lookup_isbn",
        side_effect=requests.exceptions.ConnectionError("timeout"),
    ):
        result = import_goodreads_csv(file)

    assert result.added == 1
    assert Book.objects.filter(title="Enriched Fail Book").exists()


@pytest.mark.django_db
def test_isbn_import_paces_lookups(settings):
    settings.METADATA_IMPORT_DELAY_SECONDS = 0.5
    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.return_value = {
            "title": "Paced Book",
            "authors": ["Author"],
        }
        with patch("books.import_export.time.sleep") as mock_sleep:
            import_isbns(["9780143127550", "9780141439518"])

    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(0.5)
