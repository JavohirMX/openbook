from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status

from accounts.models import UserProfile
from books.factories import AuthorFactory, BookAuthorFactory, BookFactory, GenreFactory, ReviewFactory
from books.models import Quote, ReadingLog, ReadingStatus


@pytest.mark.django_db
class TestAuthorAPI:
    def test_list_authors(self, authenticated_client):
        author = AuthorFactory(name="Jane Austen")
        book = BookFactory()
        BookAuthorFactory(book=book, author=author)

        response = authenticated_client.get(reverse("author-list"))
        assert response.status_code == status.HTTP_200_OK
        names = [item["name"] for item in response.data["data"]]
        assert "Jane Austen" in names

    def test_author_detail(self, authenticated_client):
        author = AuthorFactory(name="Tolkien")
        book = BookFactory()
        BookAuthorFactory(book=book, author=author)

        response = authenticated_client.get(reverse("author-detail", args=[author.pk]))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["data"]["book_count"] == 1


@pytest.mark.django_db
class TestGenreAPI:
    def test_genre_detail_by_slug(self, authenticated_client):
        genre = GenreFactory(name="Fantasy", slug="fantasy")
        book = BookFactory()
        book.genres.add(genre)

        response = authenticated_client.get(reverse("genre-detail", args=["fantasy"]))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"]["book_count"] == 1


@pytest.mark.django_db
class TestBookFilters:
    def test_filter_by_rating(self, authenticated_client):
        rated = BookFactory(title="Rated Book")
        ReviewFactory(book=rated, rating=5)
        unrated = BookFactory(title="Unrated Book")

        response = authenticated_client.get(reverse("book-list"), {"rating": 5})
        assert response.status_code == status.HTTP_200_OK
        ids = {item["id"] for item in response.data["data"]}
        assert str(rated.pk) in ids
        assert str(unrated.pk) not in ids


@pytest.mark.django_db
class TestReadingHistoryAPI:
    def test_reading_history_endpoint(self, authenticated_client):
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.READING
        log.started_at = log.updated_at.date()
        log.save()

        response = authenticated_client.get(reverse("book-reading-history", args=[book.pk]))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["book_id"] == str(book.pk)
        assert any(event["kind"] == "started" for event in response.data["events"])


@pytest.mark.django_db
class TestQuotesAPI:
    def test_create_and_list_quotes(self, authenticated_client):
        book = BookFactory()

        create = authenticated_client.post(
            reverse("book-quotes", args=[book.pk]),
            {"text": "It was the best of times.", "position": "p. 1"},
            format="json",
        )
        assert create.status_code == status.HTTP_201_CREATED

        listing = authenticated_client.get(reverse("book-quotes", args=[book.pk]))
        assert listing.status_code == status.HTTP_200_OK
        assert len(listing.json()["data"]) == 1
        assert Quote.objects.filter(book=book).count() == 1


@pytest.mark.django_db
class TestMetadataSearchAPI:
    def test_search_metadata(self, authenticated_client):
        mock_results = [{"title": "Dune", "authors": ["Frank Herbert"], "isbn_13": "9780441172719"}]
        with patch("books.views.MetadataService.search_books", return_value=mock_results):
            response = authenticated_client.get(
                reverse("book-search-metadata"),
                {"q": "Dune"},
            )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"][0]["title"] == "Dune"


@pytest.mark.django_db
class TestProviderLinksAPI:
    def test_provider_links(self, authenticated_client):
        book = BookFactory(isbn_13="9780306406157", google_books_id="abc123", title="Example Book")
        response = authenticated_client.get(reverse("book-provider-links", args=[book.pk]))
        assert response.status_code == status.HTTP_200_OK
        names = {link["name"] for link in response.data["links"]}
        assert "Google Books" in names
        assert "Amazon" in names
        assert "Project Gutenberg" in names
        assert "Internet Archive" in names


@pytest.mark.django_db
class TestEmbedAPI:
    def test_embed_requires_valid_key(self, api_client, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.embed_enabled = True
        profile.embed_key = "secret-key"
        profile.save()

        ok = api_client.get(reverse("api-embed"), {"key": "secret-key"})
        assert ok.status_code == status.HTTP_200_OK
        assert "books" in ok.data

        bad = api_client.get(reverse("api-embed"), {"key": "wrong"})
        assert bad.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestJeluFeatureWebViews:
    def test_author_list_page(self, client, user):
        client.force_login(user)
        AuthorFactory(name="Ada Lovelace")
        response = client.get(reverse("web:author-list"))
        assert response.status_code == 200
        assert b"Ada Lovelace" in response.content

    def test_genre_detail_page(self, client, user):
        client.force_login(user)
        genre = GenreFactory(name="Sci-Fi", slug="sci-fi")
        book = BookFactory()
        book.genres.add(genre)
        response = client.get(reverse("web:genre-detail", args=["sci-fi"]))
        assert response.status_code == 200
        assert book.title.encode() in response.content

    def test_metadata_search_partial(self, client, user):
        client.force_login(user)
        with patch(
            "books.web_views.MetadataService.search_books",
            return_value=[{"title": "1984", "authors": ["Orwell"]}],
        ):
            response = client.get(reverse("web:book-search-metadata"), {"q": "1984"})
        assert response.status_code == 200
        assert b"1984" in response.content

    def test_embed_widget_js(self, api_client, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.embed_enabled = True
        profile.embed_key = "widget-key"
        profile.save()
        response = api_client.get(reverse("web:embed-widget"), {"key": "widget-key"})
        assert response.status_code == 200
        assert b"openbook-embed" in response.content
