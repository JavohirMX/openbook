from datetime import date, timedelta
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.factories import UserFactory
from books.factories import BookFactory, ReadingProgressFactory
from books.models import ReadingLog, ReadingStatus
from books.stats import (
    finish_calendar_grid,
    finish_calendar_strip,
    monthly_reads_for_year,
    pages_per_month_for_year,
    parse_stats_year_month,
    stats_available_years,
)


@pytest.fixture
def web_user(db):
    return UserFactory(email="stats@example.com", password="password123")


@pytest.fixture
def logged_in_client(client, web_user):
    client.login(username="stats@example.com", password="password123")
    return client


@pytest.mark.django_db
class TestYearScopedStats:
    def test_monthly_reads_for_year_fills_twelve_months(self):
        year = timezone.localdate().year
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = date(year, 3, 15)
        log.save()

        rows = monthly_reads_for_year(year)
        assert len(rows) == 12
        assert rows[0] == {"month": f"{year}-01", "count": 0}
        assert rows[2] == {"month": f"{year}-03", "count": 1}
        assert rows[11]["month"] == f"{year}-12"

    def test_pages_per_month_for_year_fills_twelve_months(self):
        year = timezone.localdate().year
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        ReadingProgressFactory(
            reading_log=log,
            book=book,
            pages_read=42,
            logged_on=date(year, 5, 10),
        )

        rows = pages_per_month_for_year(year)
        assert len(rows) == 12
        assert rows[4] == {"month": f"{year}-05", "pages": 42}
        assert rows[0]["pages"] == 0

    def test_stats_available_years_from_first_activity(self):
        year = timezone.localdate().year
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        ReadingProgressFactory(
            reading_log=log,
            book=book,
            pages_read=5,
            logged_on=date(year - 2, 7, 1),
        )

        years = stats_available_years()
        assert years[0] == year - 2
        assert years[-1] == year

    def test_stats_available_years_from_finishes_without_progress(self):
        year = timezone.localdate().year
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = date(year - 3, 4, 12)
        log.save()

        years = stats_available_years()
        assert years[0] == year - 3
        assert years[-1] == year

    def test_finish_calendar_grid_monday_alignment_and_padding(self):
        grid = finish_calendar_grid(2024, 6)
        assert grid["weekday_labels"] == ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        assert grid["label"] == "June 2024"

        first_week = grid["weeks"][0]
        assert first_week[0]["day"] == 0
        assert first_week[5]["day"] == 1
        assert first_week[5]["count"] == 0
        assert first_week[5]["intensity"] == 0

    def test_finish_calendar_grid_tracks_max_count_and_today(self):
        year = timezone.localdate().year
        month = timezone.localdate().month
        today = timezone.localdate().day

        for offset in range(3):
            book = BookFactory(title=f"Finish {offset}")
            log = ReadingLog.objects.get(book=book)
            log.status = ReadingStatus.FINISHED
            log.finished_at = date(year, month, today)
            log.save()

        grid = finish_calendar_grid(year, month)
        assert grid["max_count"] == 3
        today_cell = next(
            cell
            for week in grid["weeks"]
            for cell in week
            if cell["day"] == today
        )
        assert today_cell["count"] == 3
        assert today_cell["is_today"] is True
        assert today_cell["intensity"] == 4

    def test_finish_calendar_strip_shows_up_to_three_months(self):
        year = 2024
        strip = finish_calendar_strip(year, 6, count=3)
        assert len(strip["calendars"]) == 3
        assert strip["calendars"][0]["month"] == 4
        assert strip["calendars"][-1]["month"] == 6
        assert strip["range_label"] == "April – June 2024"

    def test_finish_calendar_strip_shared_intensity_scale(self):
        year = timezone.localdate().year
        month = timezone.localdate().month
        if month < 2:
            pytest.skip("Need at least two months in current year")

        for _ in range(2):
            book = BookFactory()
            log = ReadingLog.objects.get(book=book)
            log.status = ReadingStatus.FINISHED
            log.finished_at = date(year, month, 1)
            log.save()

        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = date(year, month - 1, 1)
        log.save()

        strip = finish_calendar_strip(year, month, count=2)
        prev_month_cal = strip["calendars"][0]
        current_month_cal = strip["calendars"][1]

        def day_one_count(calendar):
            for week in calendar["weeks"]:
                for cell in week:
                    if cell["day"] == 1:
                        return cell["count"], cell["intensity"]
            raise AssertionError("day 1 not found")

        prev_count, prev_intensity = day_one_count(prev_month_cal)
        current_count, current_intensity = day_one_count(current_month_cal)
        assert prev_count == 1
        assert current_count == 2
        assert prev_intensity == 2
        assert current_intensity == 4

    def test_parse_stats_year_month_defaults_and_clamps(self):
        today = timezone.localdate()
        year, month = parse_stats_year_month(None, None)
        assert year == today.year
        assert month == today.month

        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        ReadingProgressFactory(
            reading_log=log,
            book=book,
            pages_read=1,
            logged_on=date(today.year - 1, 6, 1),
        )
        year, month = parse_stats_year_month(str(today.year - 1), "12")
        assert year == today.year - 1
        assert month == 12

        year, month = parse_stats_year_month(str(today.year), "12")
        assert month == min(12, today.month)


@pytest.mark.django_db
class TestStatsWebViews:
    def test_stats_page_year_query_shows_twelve_months(self, logged_in_client):
        year = timezone.localdate().year
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = date(year, 2, 1)
        log.save()

        response = logged_in_client.get(reverse("web:stats"), {"year": year})
        assert response.status_code == 200
        content = response.content.decode()
        assert f'"{year}-01"' in content or f'"{year}-02"' in content
        assert "year-select" in content
        assert "Finish Calendar" in content

    def test_finished_on_day_lists_books(self, logged_in_client):
        book = BookFactory(title="Calendar Winner")
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = date(2024, 6, 15)
        log.save()

        response = logged_in_client.get(
            reverse("web:stats-finished-on", kwargs={"year": 2024, "month": 6, "day": 15})
        )
        assert response.status_code == 200
        assert "Calendar Winner" in response.content.decode()

    def test_finished_on_invalid_date_returns_404(self, logged_in_client):
        response = logged_in_client.get(
            reverse("web:stats-finished-on", kwargs={"year": 2024, "month": 2, "day": 30})
        )
        assert response.status_code == 404

    def test_stats_htmx_year_scope_returns_oob_partial(self, logged_in_client):
        year = timezone.localdate().year
        book = BookFactory()
        log = ReadingLog.objects.get(book=book)
        log.status = ReadingStatus.FINISHED
        log.finished_at = date(year, 3, 10)
        log.save()

        response = logged_in_client.get(
            reverse("web:stats"),
            {"year": year},
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="stats-year-controls"' in content
        assert 'hx-swap-oob="true"' in content
        assert 'id="stats-finish-calendar"' in content
        assert "page-title" not in content

        trigger = json.loads(response["HX-Trigger"])
        assert len(trigger["statsYearUpdated"]["monthly"]) == 12
        assert len(trigger["statsYearUpdated"]["pages"]) == 12
        assert trigger["statsYearUpdated"]["monthly"][2]["count"] == 1

    def test_stats_full_page_without_htmx(self, logged_in_client):
        BookFactory()
        response = logged_in_client.get(reverse("web:stats"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "Reading Stats" in content
        assert "HX-Trigger" not in response
