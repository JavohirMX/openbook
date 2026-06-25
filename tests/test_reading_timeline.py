from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.factories import UserFactory
from books.factories import BookFactory, ReadingProgressFactory
from books.models import ReadingLog, ReadingStatus
from books.reading_timeline import build_reading_timeline


@pytest.fixture
def web_user(db):
    return UserFactory(email="web@example.com", password="password123")


@pytest.fixture
def logged_in_client(client, web_user):
    client.login(username="web@example.com", password="password123")
    return client


@pytest.mark.django_db
def test_build_reading_timeline_sorts_mixed_entries():
    book = BookFactory()
    log = ReadingLog.objects.get(book=book)
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    log.status = ReadingStatus.FINISHED
    log.started_at = yesterday
    log.finished_at = today
    log.save()

    ReadingProgressFactory(
        book=book,
        reading_log=log,
        logged_on=yesterday,
        progress_percent=50,
    )

    timeline = build_reading_timeline(log)

    assert len(timeline) >= 2
    assert timeline[0].logged_on >= timeline[1].logged_on
    kinds = {entry.kind for entry in timeline}
    assert "progress" in kinds
    assert "finished" in kinds


@pytest.mark.django_db
def test_book_detail_with_timeline_loads(logged_in_client):
    book = BookFactory()
    log = ReadingLog.objects.get(book=book)
    log.status = ReadingStatus.FINISHED
    log.started_at = timezone.localdate() - timedelta(days=3)
    log.finished_at = timezone.localdate()
    log.save()
    ReadingProgressFactory(book=book, reading_log=log, progress_percent=25)

    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    assert response.status_code == 200
