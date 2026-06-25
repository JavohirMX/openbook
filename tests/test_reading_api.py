from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from books.factories import BookFactory
from books.models import ReadingLog, ReadingProgress, ReadingStatus, Review


@pytest.mark.django_db
class TestReviewAPI:
    def test_get_review_not_found(self, authenticated_client):
        book = BookFactory()

        response = authenticated_client.get(reverse("book-review", args=[book.pk]))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_review_upsert_and_delete(self, authenticated_client):
        book = BookFactory()

        created = authenticated_client.put(
            reverse("book-review", args=[book.pk]),
            {"rating": 5, "review_text": "Excellent"},
            format="json",
        )
        assert created.status_code == status.HTTP_200_OK
        data = created.json()["data"]
        assert data["rating"] == 5
        assert data["review_text"] == "Excellent"
        assert Review.objects.filter(book=book).count() == 1

        updated = authenticated_client.put(
            reverse("book-review", args=[book.pk]),
            {"rating": 4, "review_text": "Still great"},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK
        assert Review.objects.filter(book=book).count() == 1
        review = Review.objects.get(book=book)
        assert review.rating == 4
        assert review.review_text == "Still great"

        fetched = authenticated_client.get(reverse("book-review", args=[book.pk]))
        assert fetched.status_code == status.HTTP_200_OK
        assert fetched.json()["data"]["rating"] == 4

        deleted = authenticated_client.delete(reverse("book-review", args=[book.pk]))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not Review.objects.filter(book=book).exists()


@pytest.mark.django_db
class TestReadingAPI:
    def test_reading_log_auto_created_with_book(self, authenticated_client):
        book = BookFactory(pages=320)

        response = authenticated_client.get(reverse("book-reading", args=[book.pk]))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["status"] == ReadingStatus.NOT_STARTED
        assert data["total_pages"] == 320
        assert data["progress_history"] == []
        assert ReadingLog.objects.filter(book=book).exists()

    def test_not_started_to_reading_sets_started_at(self, authenticated_client, monkeypatch):
        today = timezone.localdate()
        book = BookFactory()
        reading_log = ReadingLog.objects.get(book=book)
        assert reading_log.started_at is None

        response = authenticated_client.put(
            reverse("book-reading", args=[book.pk]),
            {"status": ReadingStatus.READING},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        reading_log.refresh_from_db()
        assert reading_log.status == ReadingStatus.READING
        assert reading_log.started_at == today
        assert ReadingProgress.objects.filter(reading_log=reading_log).count() == 0

    def test_reading_to_finished_increments_read_count(self, authenticated_client):
        book = BookFactory(pages=200)
        reading_log = ReadingLog.objects.get(book=book)
        reading_log.status = ReadingStatus.READING
        reading_log.started_at = timezone.localdate()
        reading_log.total_pages = 200
        reading_log.save()

        response = authenticated_client.put(
            reverse("book-reading", args=[book.pk]),
            {"status": ReadingStatus.FINISHED},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        reading_log.refresh_from_db()
        assert reading_log.status == ReadingStatus.FINISHED
        assert reading_log.finished_at == timezone.localdate()
        assert reading_log.progress_percent == 100
        assert reading_log.current_page == 200
        assert reading_log.read_count == 1
        assert ReadingProgress.objects.filter(reading_log=reading_log).count() == 1

    def test_finished_to_reading_clears_finished_at(self, authenticated_client):
        book = BookFactory()
        reading_log = ReadingLog.objects.get(book=book)
        reading_log.status = ReadingStatus.FINISHED
        reading_log.finished_at = timezone.localdate() - timedelta(days=10)
        reading_log.read_count = 1
        reading_log.save()

        response = authenticated_client.put(
            reverse("book-reading", args=[book.pk]),
            {"status": ReadingStatus.READING},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        reading_log.refresh_from_db()
        assert reading_log.status == ReadingStatus.READING
        assert reading_log.finished_at is None
        assert reading_log.started_at == timezone.localdate()

    def test_progress_update_creates_history_entry(self, authenticated_client):
        book = BookFactory()
        reading_log = ReadingLog.objects.get(book=book)
        reading_log.status = ReadingStatus.READING
        reading_log.started_at = timezone.localdate()
        reading_log.save()

        response = authenticated_client.put(
            reverse("book-reading", args=[book.pk]),
            {
                "progress_percent": 42,
                "current_page": 84,
                "pages_read": 20,
                "note": "Good chapter",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["progress_percent"] == 42
        assert data["current_page"] == 84
        assert len(data["progress_history"]) == 1
        entry = data["progress_history"][0]
        assert entry["logged_on"] == timezone.localdate().isoformat()
        assert entry["progress_percent"] == 42
        assert entry["pages_read"] == 20
        assert entry["note"] == "Good chapter"

    def test_reread_finish_increments_read_count_again(self, authenticated_client):
        book = BookFactory()
        reading_log = ReadingLog.objects.get(book=book)
        reading_log.status = ReadingStatus.READING
        reading_log.started_at = timezone.localdate()
        reading_log.read_count = 1
        reading_log.save()

        response = authenticated_client.put(
            reverse("book-reading", args=[book.pk]),
            {"status": ReadingStatus.FINISHED},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        reading_log.refresh_from_db()
        assert reading_log.read_count == 2
