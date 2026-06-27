from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status

from books.factories import (
    AuthorFactory,
    BookAuthorFactory,
    BookFactory,
    BookshelfItemFactory,
    GenreFactory,
    ShelfFactory,
)
from books.models import Book, ReadingLog, ReadingStatus


VALID_ISBN_13 = "9780306406157"
VALID_ISBN_10 = "0306406152"
INVALID_CHECKSUM_ISBN = "9780000000000"

OL_LOOKUP_RESPONSE = {
    "ISBN:9780306406157": {
        "title": "Lookup Title",
        "authors": [{"name": "Lookup Author"}],
        "number_of_pages": 220,
        "publishers": [{"name": "Lookup Publisher"}],
        "subjects": [{"name": "Fiction"}, {"name": "Mystery"}],
        "cover": {
            "large": "https://covers.openlibrary.org/b/isbn/9780306406157-L.jpg",
            "medium": "https://covers.openlibrary.org/b/isbn/9780306406157-M.jpg",
        },
    }
}

GOOGLE_LOOKUP_RESPONSE = {
    "items": [
        {
            "volumeInfo": {
                "title": "Google Title",
                "authors": ["Google Author"],
                "pageCount": 180,
                "publisher": "Google Publisher",
                "categories": ["Science"],
                "imageLinks": {
                    "thumbnail": "https://books.google.com/thumb.jpg",
                },
            }
        }
    ]
}


@pytest.fixture
def books_list_url():
    return reverse("book-list")


@pytest.fixture
def book_detail_url():
    def _url(book_id):
        return reverse("book-detail", args=[book_id])

    return _url


def _mock_response(json_data, status_code=200):
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = json_data
    mock.raise_for_status = MagicMock()
    return mock


@pytest.mark.django_db
class TestBooksCRUD:
    def test_create_book_returns_envelope(self, authenticated_client, books_list_url):
        payload = {
            "title": "New Book",
            "author_names": ["Alice Writer"],
            "genre_names": ["Fiction"],
            "isbn_13": VALID_ISBN_13,
        }

        with patch.object(
            __import__("books.metadata", fromlist=["MetadataService"]).MetadataService,
            "_get",
            return_value=_mock_response({}),
        ):
            response = authenticated_client.post(books_list_url, payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["data"]["title"] == "New Book"
        assert body["data"]["authors"][0]["name"] == "Alice Writer"
        assert body["data"]["status"] == ReadingStatus.NOT_STARTED
        assert ReadingLog.objects.filter(book_id=body["data"]["id"]).exists()

    def test_list_books_pagination_envelope(self, authenticated_client, books_list_url):
        BookFactory.create_batch(3)

        response = authenticated_client.get(books_list_url)

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "data" in body
        assert "meta" in body
        assert body["meta"]["page"] == 1
        assert body["meta"]["per_page"] == 20
        assert body["meta"]["total"] == 3
        assert len(body["data"]) == 3

    def test_retrieve_book(self, authenticated_client, book_detail_url):
        book = BookFactory(title="Detail Book")
        BookAuthorFactory(book=book, author=AuthorFactory(name="Detail Author"))

        response = authenticated_client.get(book_detail_url(book.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["title"] == "Detail Book"
        assert response.json()["data"]["authors"][0]["name"] == "Detail Author"

    def test_update_book(self, authenticated_client, book_detail_url):
        book = BookFactory(title="Old Title")

        response = authenticated_client.patch(
            book_detail_url(book.id),
            {"title": "Updated Title"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["title"] == "Updated Title"
        book.refresh_from_db()
        assert book.title == "Updated Title"

    def test_patch_upload_cover(self, authenticated_client, book_detail_url, settings, tmp_path):
        import io

        settings.MEDIA_ROOT = tmp_path
        book = BookFactory(title="API Cover Book", cover_url="https://example.com/cover.jpg")
        upload = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * 2000)
        upload.name = "cover.jpg"
        response = authenticated_client.patch(
            book_detail_url(book.id),
            {"cover_image": upload},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK
        book.refresh_from_db()
        assert book.cover_image
        assert "cover_url" in book.metadata_locked_fields
        assert response.json()["data"]["cover_url"]

    def test_patch_clear_cover(self, authenticated_client, book_detail_url, settings, tmp_path):
        from django.core.files.base import ContentFile

        settings.MEDIA_ROOT = tmp_path
        book = BookFactory(cover_url="https://example.com/cover.jpg")
        book.cover_image.save(f"{book.pk}.jpg", ContentFile(b"\xff\xd8\xff\xe0" + b"\x00" * 2000), save=True)
        response = authenticated_client.patch(
            book_detail_url(book.id),
            {"clear_cover": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        book.refresh_from_db()
        assert not book.cover_image
        assert book.cover_url == "https://example.com/cover.jpg"


@pytest.mark.django_db
class TestBooksSearchAndFilter:
    def test_search_by_title(self, authenticated_client, books_list_url):
        book = BookFactory(title="Unique Searchable Title")
        BookFactory(title="Other Book")

        response = authenticated_client.get(books_list_url, {"search": "Searchable"})

        assert response.status_code == status.HTTP_200_OK
        ids = [item["id"] for item in response.json()["data"]]
        assert str(book.id) in ids
        assert len(ids) == 1

    def test_search_exact_isbn(self, authenticated_client, books_list_url):
        book = BookFactory(isbn_13=VALID_ISBN_13)
        BookFactory(isbn_13="9780143127741")

        response = authenticated_client.get(books_list_url, {"search": VALID_ISBN_13})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["id"] == str(book.id)

    def test_filter_by_author(self, authenticated_client, books_list_url):
        author = AuthorFactory(name="Filter Author")
        book = BookFactory()
        BookAuthorFactory(book=book, author=author)
        BookFactory()

        response = authenticated_client.get(
            books_list_url, {"author": "Filter Author"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["id"] == str(book.id)

    def test_filter_by_isbn(self, authenticated_client, books_list_url):
        book = BookFactory(isbn_13=VALID_ISBN_13)
        BookFactory()

        response = authenticated_client.get(books_list_url, {"isbn": VALID_ISBN_13})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["id"] == str(book.id)

    def test_filter_by_shelf(self, authenticated_client, books_list_url):
        shelf = ShelfFactory()
        book = BookFactory()
        BookshelfItemFactory(book=book, shelf=shelf)
        BookFactory()

        response = authenticated_client.get(
            books_list_url, {"shelf": shelf.id}
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["id"] == str(book.id)

    def test_filter_by_genre(self, authenticated_client, books_list_url):
        genre = GenreFactory(name="Sci-Fi", slug="sci-fi")
        book = BookFactory()
        book.genres.add(genre)
        BookFactory()

        response = authenticated_client.get(books_list_url, {"genre": "sci-fi"})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["id"] == str(book.id)

    def test_filter_by_status(self, authenticated_client, books_list_url):
        book = BookFactory()
        book.reading_log.status = ReadingStatus.READING
        book.reading_log.save(update_fields=["status"])
        other = BookFactory()
        other.reading_log.status = ReadingStatus.FINISHED
        other.reading_log.save(update_fields=["status"])

        response = authenticated_client.get(
            books_list_url, {"status": ReadingStatus.READING}
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1
        assert response.json()["data"][0]["id"] == str(book.id)


@pytest.mark.django_db
class TestBooksLookup:
    def test_lookup_open_library_success(self, authenticated_client, settings):
        settings.CACHES = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        }
        url = reverse("book-lookup")

        with patch(
            "books.metadata.MetadataService._get",
            return_value=_mock_response(OL_LOOKUP_RESPONSE),
        ) as mock_get:
            response = authenticated_client.get(url, {"isbn": VALID_ISBN_13})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["title"] == "Lookup Title"
        assert data["authors"] == ["Lookup Author"]
        assert data["pages"] == 220
        assert data["publisher"] == "Lookup Publisher"
        assert "Fiction" in data["genres"]
        assert mock_get.called

    def test_lookup_google_fallback(self, authenticated_client, settings):
        settings.CACHES = {
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
        }
        from django.core.cache import cache

        cache.clear()
        url = reverse("book-lookup")

        def side_effect(request_url, params=None, **kwargs):
            if "/api/books" in request_url:
                return _mock_response({})
            return _mock_response(GOOGLE_LOOKUP_RESPONSE)

        with patch("books.metadata.MetadataService._get", side_effect=side_effect):
            response = authenticated_client.get(url, {"isbn": VALID_ISBN_13})

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["title"] == "Google Title"
        assert data["authors"] == ["Google Author"]
        assert data["cover_url"] == "https://books.google.com/thumb.jpg"


@pytest.mark.django_db
class TestBooksSoftDelete:
    def test_soft_delete_restore_and_trash(self, authenticated_client, book_detail_url):
        book = BookFactory(title="Trash Me")

        delete_response = authenticated_client.delete(book_detail_url(book.id))
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT
        assert not Book.objects.filter(pk=book.id).exists()
        assert Book.all_objects.filter(pk=book.id, deleted_at__isnull=False).exists()

        list_response = authenticated_client.get(reverse("book-list"))
        assert len(list_response.json()["data"]) == 0

        trash_response = authenticated_client.get(reverse("book-trash"))
        assert trash_response.status_code == status.HTTP_200_OK
        assert len(trash_response.json()["data"]) == 1

        restore_response = authenticated_client.post(
            reverse("book-restore", args=[book.id])
        )
        assert restore_response.status_code == status.HTTP_200_OK
        assert Book.objects.filter(pk=book.id).exists()

    def test_permanent_delete(self, authenticated_client, book_detail_url):
        book = BookFactory()
        book_id = book.id

        response = authenticated_client.delete(
            f"{book_detail_url(book_id)}?permanent=true"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Book.all_objects.filter(pk=book_id).exists()


@pytest.mark.django_db
class TestBooksISBNValidation:
    def test_duplicate_isbn_returns_409(self, authenticated_client, books_list_url):
        existing = BookFactory(isbn_13=VALID_ISBN_13)

        response = authenticated_client.post(
            books_list_url,
            {"title": "Duplicate", "isbn_13": VALID_ISBN_13},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        body = response.json()
        assert body["error"]["code"] == "duplicate_isbn"
        assert body["error"]["details"]["existing_book_id"] == str(existing.id)

    def test_invalid_checksum_is_accepted_with_warning(
        self, authenticated_client, books_list_url
    ):
        payload = {
            "title": "Bad Checksum Book",
            "isbn_13": INVALID_CHECKSUM_ISBN,
        }

        with patch(
            "books.metadata.MetadataService.lookup_isbn",
            return_value={},
        ):
            response = authenticated_client.post(books_list_url, payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["data"]["isbn_13"] == INVALID_CHECKSUM_ISBN
        assert "meta" in body
        assert any("checksum" in w.lower() for w in body["meta"]["warnings"])


@pytest.mark.django_db
def test_books_require_authentication(api_client, books_list_url):
    response = api_client.get(books_list_url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
