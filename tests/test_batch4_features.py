import csv
import io
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from books.factories import (
    BookAuthorFactory,
    BookFactory,
    BookGenreFactory,
    GenreFactory,
    SeriesFactory,
)
from books.genre_normalize import normalize_user_genre_name
from books.import_export import import_goodreads_csv
from books.models import AuthorRole, Book, BookAuthor, Genre
from books.services import delete_genre, merge_genres, rename_genre


@pytest.mark.django_db
class TestSeriesAPI:
    def test_list_series(self, authenticated_client):
        series = SeriesFactory(name="Mistborn", slug="mistborn")
        BookFactory(title="The Final Empire", series=series, series_position=Decimal("1"))

        response = authenticated_client.get(reverse("series-list"))
        assert response.status_code == status.HTTP_200_OK
        slugs = [item["slug"] for item in response.json()["data"]]
        assert "mistborn" in slugs

    def test_retrieve_series(self, authenticated_client):
        series = SeriesFactory(name="Stormlight", slug="stormlight")
        response = authenticated_client.get(reverse("series-detail", args=["stormlight"]))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["name"] == "Stormlight"

    def test_book_includes_series(self, authenticated_client):
        series = SeriesFactory(name="Dune", slug="dune")
        book = BookFactory(title="Dune", series=series, series_position=Decimal("1"))
        response = authenticated_client.get(reverse("book-detail", args=[book.pk]))
        data = response.json()["data"]
        assert data["series"]["slug"] == "dune"
        assert data["series_position"] == "1.00"

    def test_create_book_with_series_name(self, authenticated_client):
        response = authenticated_client.post(
            reverse("book-list"),
            {
                "title": "Book One",
                "series_name": "Wheel of Time",
                "series_position": "1",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        book = Book.objects.get(title="Book One")
        assert book.series.name == "Wheel of Time"
        assert book.series_position == Decimal("1")

    def test_filter_books_by_series_slug(self, authenticated_client):
        series = SeriesFactory(slug="expanse")
        BookFactory(series=series)
        BookFactory()
        response = authenticated_client.get(reverse("book-list"), {"series": "expanse"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()["data"]) == 1


@pytest.mark.django_db
def test_goodreads_import_series_columns(settings):
    settings.IMPORT_GOODREADS_ENRICH_METADATA = False
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
        "Series", "#",
    ])
    writer.writerow([
        "The Fellowship of the Ring", "J.R.R. Tolkien", "", "", "5", "",
        "400", "1954", "Allen", "read", "",
        "The Lord of the Rings", "1",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "goodreads.csv"
    with patch("books.webhooks.emit_event", return_value=0):
        result = import_goodreads_csv(file)
    assert result.added == 1
    book = Book.objects.get(title="The Fellowship of the Ring")
    assert book.series.name == "The Lord of the Rings"
    assert book.series_position == Decimal("1")


@pytest.mark.django_db
class TestGenreManagementAPI:
    def test_rename_genre(self, authenticated_client):
        genre = GenreFactory(name="Sci Fi", slug="sci-fi")
        response = authenticated_client.patch(
            reverse("genre-detail", args=["sci-fi"]),
            {"name": "Science Fiction"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        genre.refresh_from_db()
        assert genre.name == "Science Fiction"

    def test_merge_genres(self, authenticated_client):
        source = GenreFactory(name="Scifi", slug="scifi")
        target = GenreFactory(name="Science Fiction", slug="science-fiction")
        book = BookFactory()
        book.genres.add(source)

        response = authenticated_client.patch(
            reverse("genre-detail", args=["scifi"]),
            {"merge_into": "science-fiction"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert not Genre.objects.filter(slug="scifi").exists()
        assert book.genres.filter(slug="science-fiction").exists()

    def test_delete_genre_requires_reassign(self, authenticated_client):
        genre = GenreFactory(slug="orphan")
        book = BookFactory()
        book.genres.add(genre)

        response = authenticated_client.delete(reverse("genre-detail", args=["orphan"]))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_delete_genre_with_reassign(self, authenticated_client):
        source = GenreFactory(name="Old", slug="old")
        target = GenreFactory(name="New", slug="new")
        book = BookFactory()
        book.genres.add(source)

        response = authenticated_client.delete(
            reverse("genre-detail", args=["old"]),
            {"reassign_to": "new"},
            format="json",
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Genre.objects.filter(slug="old").exists()
        assert book.genres.filter(slug="new").exists()


@pytest.mark.django_db
class TestGenreServices:
    def test_rename_normalizes_canonical_name(self):
        genre = GenreFactory(name="scifi", slug="scifi")
        updated = rename_genre(genre, "science fiction")
        assert updated.name == "Science Fiction"

    def test_merge_and_delete(self):
        a = GenreFactory(name="A", slug="a")
        b = GenreFactory(name="B", slug="b")
        empty = GenreFactory(name="Empty", slug="empty")
        book = BookFactory()
        BookGenreFactory(book=book, genre=a)
        merge_genres(a, b)
        assert book.genres.filter(pk=b.pk).exists()
        delete_genre(empty)
        assert not Genre.objects.filter(slug="empty").exists()


@pytest.mark.django_db
class TestSeriesWeb:
    def test_series_detail_page(self, logged_in_client):
        series = SeriesFactory(name="Discworld", slug="discworld")
        BookFactory(title="Guards! Guards!", series=series, series_position=Decimal("8"))
        response = logged_in_client.get(reverse("web:series-detail", args=["discworld"]))
        assert response.status_code == 200
        assert b"Discworld" in response.content
        assert b"Guards! Guards!" in response.content

    def test_book_list_filter_by_series(self, logged_in_client):
        series = SeriesFactory(slug="hitchhiker")
        BookFactory(title="Volume One", series=series)
        BookFactory(title="Standalone")
        response = logged_in_client.get(reverse("web:book-list"), {"series": "hitchhiker"})
        assert response.status_code == 200
        assert b"Volume One" in response.content
        assert b"Standalone" not in response.content

    def test_book_detail_shows_series_badge(self, logged_in_client):
        series = SeriesFactory(name="Earthsea", slug="earthsea")
        book = BookFactory(title="A Wizard of Earthsea", series=series, series_position=Decimal("1"))
        response = logged_in_client.get(reverse("web:book-detail", args=[book.pk]))
        assert response.status_code == 200
        assert b"Earthsea" in response.content
        assert b"#1" in response.content


@pytest.mark.django_db
class TestAuthorRolesWeb:
    def test_book_add_with_contributor_roles(self, logged_in_client):
        response = logged_in_client.post(
            reverse("web:book-add"),
            {
                "title": "Translated Work",
                "author_names": "Original Author",
                "translator_names": "Jane Translator",
                "editor_names": "Bob Editor",
                "illustrator_names": "Art Person",
                "language": "en",
            },
        )
        assert response.status_code == 302
        book = Book.objects.get(title="Translated Work")
        roles = set(BookAuthor.objects.filter(book=book).values_list("role", flat=True))
        assert AuthorRole.AUTHOR in roles
        assert AuthorRole.TRANSLATOR in roles
        assert AuthorRole.EDITOR in roles
        assert AuthorRole.ILLUSTRATOR in roles


@pytest.fixture
def logged_in_client(client, db):
    from accounts.factories import UserFactory

    user = UserFactory(email="batch4@example.com", password="password123")
    client.login(username=user.email, password="password123")
    return client


def test_normalize_user_genre_name():
    assert normalize_user_genre_name("science fiction") == "Science Fiction"
    assert normalize_user_genre_name("  Custom Label  ") == "Custom Label"
