import pytest
from django.urls import reverse

from accounts.factories import UserFactory
from books.factories import BookFactory
from books.models import ReadingStatus
from books.status_shelves import get_status_shelves


@pytest.fixture
def web_user(db):
    return UserFactory(email="web@example.com", password="password123")


@pytest.fixture
def logged_in_client(client, web_user):
    client.login(username="web@example.com", password="password123")
    return client


@pytest.mark.django_db
def test_reading_status_labels():
    assert ReadingStatus.NOT_STARTED.label == "Want to Read"
    assert ReadingStatus.FINISHED.label == "Read"
    assert ReadingStatus.READING.label == "Currently Reading"


@pytest.mark.django_db
def test_get_status_shelves_counts():
    book_wtr = BookFactory(title="Want Book")
    book_wtr.reading_log.status = ReadingStatus.NOT_STARTED
    book_wtr.reading_log.save(update_fields=["status"])

    book_reading = BookFactory(title="Reading Book")
    book_reading.reading_log.status = ReadingStatus.READING
    book_reading.reading_log.save(update_fields=["status"])

    book_read = BookFactory(title="Read Book")
    book_read.reading_log.status = ReadingStatus.FINISHED
    book_read.reading_log.save(update_fields=["status"])

    shelves = {shelf.slug: shelf for shelf in get_status_shelves()}
    assert shelves["want-to-read"].book_count == 1
    assert shelves["currently-reading"].book_count == 1
    assert shelves["read"].book_count == 1
    assert shelves["want-to-read"].name == "Want to Read"


@pytest.mark.django_db
def test_shelf_list_shows_status_shelves(logged_in_client):
    response = logged_in_client.get(reverse("web:shelf-list"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Reading shelves" in content
    assert "Want to Read" in content
    assert "Currently Reading" in content
    assert reverse("web:status-shelf-detail", kwargs={"slug": "want-to-read"}) in content


@pytest.mark.django_db
def test_status_shelf_detail_lists_books_by_status(logged_in_client):
    book = BookFactory(title="On Want List")
    book.reading_log.status = ReadingStatus.NOT_STARTED
    book.reading_log.save(update_fields=["status"])

    other = BookFactory(title="Already Reading")
    other.reading_log.status = ReadingStatus.READING
    other.reading_log.save(update_fields=["status"])

    response = logged_in_client.get(
        reverse("web:status-shelf-detail", kwargs={"slug": "want-to-read"}),
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "On Want List" in content
    assert "Already Reading" not in content


@pytest.mark.django_db
def test_status_shelf_detail_unknown_slug_returns_404(logged_in_client):
    response = logged_in_client.get(
        reverse("web:status-shelf-detail", kwargs={"slug": "does-not-exist"}),
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_paused_and_dnf_status_shelves():
    paused_book = BookFactory(title="Paused Book")
    paused_book.reading_log.status = ReadingStatus.PAUSED
    paused_book.reading_log.save(update_fields=["status"])

    dnf_book = BookFactory(title="DNF Book")
    dnf_book.reading_log.status = ReadingStatus.ABANDONED
    dnf_book.reading_log.save(update_fields=["status"])

    shelves = {shelf.slug: shelf for shelf in get_status_shelves()}
    assert shelves["paused"].book_count == 1
    assert shelves["dnf"].book_count == 1
