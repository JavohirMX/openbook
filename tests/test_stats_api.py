from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from books.factories import (
    BookFactory,
    BookGenreFactory,
    BookshelfItemFactory,
    ReadingProgressFactory,
    ShelfFactory,
)
from books.models import ReadingLog, ReadingProgress, ReadingStatus
from books.stats import _compute_reading_streak, compute_stats


@pytest.mark.django_db
class TestStatsComputation:
    def test_compute_reading_streak_consecutive_days(self):
        today = timezone.localdate()
        dates = {today, today - timedelta(days=1), today - timedelta(days=2)}
        assert _compute_reading_streak(dates) == 3

    def test_compute_reading_streak_allows_yesterday_without_today(self):
        today = timezone.localdate()
        dates = {today - timedelta(days=1), today - timedelta(days=2)}
        assert _compute_reading_streak(dates) == 2

    def test_compute_reading_streak_zero_when_gap(self):
        today = timezone.localdate()
        dates = {today, today - timedelta(days=2)}
        assert _compute_reading_streak(dates) == 1

    def test_compute_stats_aggregates(self):
        book_one = BookFactory(pages=100)
        book_two = BookFactory(pages=200)
        genre_link = BookGenreFactory(book=book_one)
        shelf = ShelfFactory(name="2026 Reads")
        BookshelfItemFactory(book=book_one, shelf=shelf)

        log_one = ReadingLog.objects.get(book=book_one)
        log_one.status = ReadingStatus.FINISHED
        log_one.finished_at = timezone.localdate().replace(day=1)
        log_one.save()

        log_two = ReadingLog.objects.get(book=book_two)
        log_two.status = ReadingStatus.READING
        log_two.save()

        ReadingProgressFactory(
            reading_log=log_two,
            book=book_two,
            pages_read=30,
            logged_on=timezone.localdate(),
        )
        ReadingProgressFactory(
            reading_log=log_two,
            book=book_two,
            pages_read=20,
            logged_on=timezone.localdate() - timedelta(days=1),
        )

        stats = compute_stats()
        assert stats["total_books"] == 2
        assert stats["completion_rate"] == 0.5
        assert stats["pages_read"] == 50
        assert stats["reading_streak"] == 2
        assert stats["books_by_shelf"] == [
            {
                "shelf_id": None,
                "slug": "want-to-read",
                "name": "Want to Read",
                "count": 0,
                "is_status_shelf": True,
            },
            {
                "shelf_id": None,
                "slug": "currently-reading",
                "name": "Currently Reading",
                "count": 1,
                "is_status_shelf": True,
            },
            {
                "shelf_id": None,
                "slug": "read",
                "name": "Read",
                "count": 1,
                "is_status_shelf": True,
            },
            {
                "shelf_id": shelf.pk,
                "name": "2026 Reads",
                "count": 1,
                "is_status_shelf": False,
            },
        ]
        assert any(
            row["genre_id"] == genre_link.genre_id and row["count"] == 1
            for row in stats["books_by_genre"]
        )
        assert any(
            row["status"] == ReadingStatus.FINISHED and row["count"] == 1
            for row in stats["books_by_status"]
        )
        assert any(
            row["status"] == ReadingStatus.READING and row["count"] == 1
            for row in stats["books_by_status"]
        )
        assert len(stats["monthly_reads"]) == 1


@pytest.mark.django_db
class TestStatsAPI:
    def test_stats_requires_auth(self, api_client):
        response = api_client.get(reverse("api-stats"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_stats_endpoint_returns_envelope(self, authenticated_client):
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = timezone.localdate()
        log.save()
        ReadingProgressFactory(
            reading_log=log,
            book=book,
            logged_on=timezone.localdate(),
            pages_read=15,
        )

        response = authenticated_client.get(reverse("api-stats"))
        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]
        assert data["total_books"] == 1
        assert data["completion_rate"] == 1.0
        assert data["pages_read"] == 15
        assert data["reading_streak"] == 1
        assert "books_by_shelf" in data
        assert "books_by_genre" in data
        assert "books_by_status" in data
        assert "monthly_reads" in data
