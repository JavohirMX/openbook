import pytest
from django.urls import reverse
from rest_framework import status

from accounts.factories import UserFactory
from books.factories import BookFactory, BookNoteFactory, QuoteFactory, ReviewFactory
from books.models import BookFormat, BookNote


@pytest.fixture
def logged_in_client(client, db):
    user = UserFactory(email="batch6@example.com", password="password123")
    client.login(username="batch6@example.com", password="password123")
    return client


@pytest.mark.django_db
class TestExtendedSearch:
    def test_search_by_review_text_api(self, authenticated_client):
        book = BookFactory(title="Obscure Title Alpha")
        ReviewFactory(book=book, review_text="serendipitous discovery phrase")
        BookFactory(title="Other Book")

        response = authenticated_client.get(reverse("book-list"), {"search": "serendipitous"})
        assert response.status_code == status.HTTP_200_OK
        ids = {item["id"] for item in response.json()["data"]}
        assert str(book.id) in ids
        assert len(ids) == 1

    def test_search_by_quote_text_api(self, authenticated_client):
        book = BookFactory(title="Another Obscure Title")
        QuoteFactory(book=book, text="whispered constellation")
        BookFactory(title="Unrelated")

        response = authenticated_client.get(reverse("book-list"), {"search": "constellation"})
        assert response.status_code == status.HTTP_200_OK
        ids = {item["id"] for item in response.json()["data"]}
        assert str(book.id) in ids

    def test_search_by_note_text_web(self, logged_in_client):
        book = BookFactory(title="Hidden Gem")
        BookNoteFactory(book=book, text="vaulted archival memory")

        response = logged_in_client.get(reverse("web:book-list"), {"search": "archival"})
        assert response.status_code == 200
        assert book.title.encode() in response.content


@pytest.mark.django_db
class TestBookFormatFields:
    def test_create_book_with_format_api(self, authenticated_client):
        response = authenticated_client.post(
            reverse("book-list"),
            {
                "title": "Audiobook Title",
                "format": BookFormat.AUDIOBOOK,
                "owned": True,
                "narrator": "Jane Narrator",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]
        assert data["format"] == BookFormat.AUDIOBOOK
        assert data["owned"] is True
        assert data["narrator"] == "Jane Narrator"

    def test_book_detail_shows_format(self, logged_in_client):
        book = BookFactory(
            title="Owned Ebook",
            format=BookFormat.EBOOK,
            owned=True,
            narrator="",
        )
        response = logged_in_client.get(reverse("web:book-detail", args=[book.pk]))
        assert response.status_code == 200
        assert b"Ebook" in response.content
        assert b"Owned" in response.content


@pytest.mark.django_db
class TestBookNote:
    def test_note_api_get_put_delete(self, authenticated_client):
        book = BookFactory()

        missing = authenticated_client.get(reverse("book-note", args=[book.pk]))
        assert missing.status_code == status.HTTP_404_NOT_FOUND

        created = authenticated_client.put(
            reverse("book-note", args=[book.pk]),
            {"text": "My **private** note"},
            format="json",
        )
        assert created.status_code == status.HTTP_200_OK
        assert created.json()["data"]["text"] == "My **private** note"

        fetched = authenticated_client.get(reverse("book-note", args=[book.pk]))
        assert fetched.status_code == status.HTTP_200_OK
        assert fetched.json()["data"]["text"] == "My **private** note"

        deleted = authenticated_client.delete(reverse("book-note", args=[book.pk]))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert BookNote.objects.filter(book=book).count() == 0

    def test_note_web_form(self, logged_in_client):
        book = BookFactory(title="Note Target")
        response = logged_in_client.post(
            reverse("web:book-note", args=[book.pk]),
            {"text": "Saved from the web UI"},
        )
        assert response.status_code == 302
        assert BookNote.objects.get(book=book).text == "Saved from the web UI"

        detail = logged_in_client.get(reverse("web:book-detail", args=[book.pk]))
        assert b"Private note" in detail.content
        assert b"Saved from the web UI" in detail.content


@pytest.mark.django_db
class TestKeyboardShortcuts:
    def test_shortcuts_script_included(self, logged_in_client):
        response = logged_in_client.get(reverse("web:dashboard"))
        assert b"shortcuts.js" in response.content

    def test_settings_documents_shortcuts(self, logged_in_client):
        response = logged_in_client.get(reverse("web:settings"))
        assert response.status_code == 200
        assert b"Keyboard shortcuts" in response.content
        assert b"Focus search" in response.content
        assert b"g b" in response.content
