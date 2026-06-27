import calendar
from datetime import date, timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from books.models import Book, BookFormat, Genre, ReadingGoal, ReadingLog, ReadingProgress, ReadingStatus, Review, Shelf

GENRE_STATS_TOP_N = 12
FINISH_CALENDAR_STRIP_MONTHS = 3


def genres_for_filter():
    return (
        Genre.objects.annotate(book_count=Count("book_genres"))
        .filter(book_count__gt=0)
        .order_by("-book_count", "name")
    )


def _books_by_genre_for_display():
    rows = list(
        Genre.objects.annotate(book_count=Count("book_genres"))
        .filter(book_count__gt=0)
        .order_by("-book_count", "name")
        .values("id", "name", "book_count")
    )
    if len(rows) <= GENRE_STATS_TOP_N:
        return [
            {"genre_id": row["id"], "name": row["name"], "count": row["book_count"]}
            for row in rows
        ]

    top = rows[:GENRE_STATS_TOP_N]
    other_count = sum(row["book_count"] for row in rows[GENRE_STATS_TOP_N:])
    result = [
        {"genre_id": row["id"], "name": row["name"], "count": row["book_count"]}
        for row in top
    ]
    if other_count:
        result.append({"genre_id": None, "name": "Other", "count": other_count})
    return result
from books.status_shelves import get_status_shelves


def _compute_reading_streak(activity_dates):
    if not activity_dates:
        return 0

    today = timezone.localdate()
    current = today
    if current not in activity_dates:
        current = today - timedelta(days=1)
        if current not in activity_dates:
            return 0

    streak = 0
    while current in activity_dates:
        streak += 1
        current -= timedelta(days=1)
    return streak


def books_finished_in_year(year: int) -> int:
    return ReadingLog.objects.filter(
        status=ReadingStatus.FINISHED,
        finished_at__year=year,
    ).count()


def pages_read_in_year(year: int) -> int:
    return (
        ReadingProgress.objects.filter(logged_on__year=year).aggregate(total=Sum("pages_read"))["total"]
        or 0
    )


def get_reading_goal(year: int) -> ReadingGoal | None:
    return ReadingGoal.objects.filter(year=year).first()


def goal_progress(year: int | None = None) -> dict:
    year = year or timezone.localdate().year
    goal = get_reading_goal(year)
    finished = books_finished_in_year(year)
    pages = pages_read_in_year(year)
    result = {
        "year": year,
        "finished_books": finished,
        "pages_read": pages,
        "target_books": goal.target_books if goal else None,
        "target_pages": goal.target_pages if goal else None,
    }
    if goal and goal.target_books:
        result["books_percent"] = min(100, int(round(finished / goal.target_books * 100)))
    if goal and goal.target_pages:
        result["pages_percent"] = min(100, int(round(pages / goal.target_pages * 100)))
    return result


def compute_year_review(year: int) -> dict:
    books_qs = (
        Book.objects.filter(
            reading_log__status=ReadingStatus.FINISHED,
            reading_log__finished_at__year=year,
        )
        .prefetch_related("genres", "authors")
        .select_related("review", "reading_log")
    )
    books = list(books_qs)
    genre_counts: dict[str, int] = {}
    rating_sum = 0
    rating_count = 0
    longest_book = None
    longest_pages = 0
    first_finished = None
    last_finished = None
    cover_books = []

    for book in books:
        for genre in book.genres.all():
            genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1
        try:
            if book.review and book.review.rating:
                rating_sum += book.review.rating
                rating_count += 1
        except Review.DoesNotExist:
            pass
        if book.pages and book.pages > longest_pages:
            longest_pages = book.pages
            longest_book = book
        finished_at = book.reading_log.finished_at
        if finished_at:
            if first_finished is None or finished_at < first_finished:
                first_finished = finished_at
            if last_finished is None or finished_at > last_finished:
                last_finished = finished_at
        if len(cover_books) < 12 and book.cover_display_url:
            cover_books.append(book)

    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    stats = compute_stats()
    return {
        "year": year,
        "books_finished": len(books),
        "pages_read": pages_read_in_year(year),
        "top_genres": [{"name": n, "count": c} for n, c in top_genres],
        "average_rating": round(rating_sum / rating_count, 1) if rating_count else None,
        "longest_streak": stats["reading_streak"],
        "goal": goal_progress(year),
        "longest_book": longest_book,
        "longest_pages": longest_pages or None,
        "first_finished": first_finished,
        "last_finished": last_finished,
        "cover_books": cover_books,
    }


def reading_activity_heatmap() -> list[dict]:
    rows = (
        ReadingProgress.objects.values("logged_on")
        .annotate(count=Count("id"))
        .order_by("logged_on")
    )
    return [{"date": row["logged_on"].isoformat(), "count": row["count"]} for row in rows]


def pages_per_month() -> list[dict]:
    return [
        {
            "month": row["month"].strftime("%Y-%m"),
            "pages": row["pages"] or 0,
        }
        for row in (
            ReadingProgress.objects.annotate(month=TruncMonth("logged_on"))
            .values("month")
            .annotate(pages=Sum("pages_read"))
            .order_by("month")
        )
    ]


def stats_available_years() -> list[int]:
    today = timezone.localdate()
    candidates = [today.year]

    first_progress = (
        ReadingProgress.objects.order_by("logged_on")
        .values_list("logged_on", flat=True)
        .first()
    )
    if first_progress:
        candidates.append(first_progress.year)

    first_finish = (
        ReadingLog.objects.filter(finished_at__isnull=False)
        .order_by("finished_at")
        .values_list("finished_at", flat=True)
        .first()
    )
    if first_finish:
        candidates.append(first_finish.year)

    return list(range(min(candidates), today.year + 1))


def _fill_year_months(year: int, rows: dict[str, int], value_key: str) -> list[dict]:
    return [
        {"month": f"{year}-{month:02d}", value_key: rows.get(f"{year}-{month:02d}", 0)}
        for month in range(1, 13)
    ]


def monthly_reads_for_year(year: int) -> list[dict]:
    rows = {
        row["month"].strftime("%Y-%m"): row["count"]
        for row in (
            ReadingLog.objects.filter(finished_at__isnull=False, finished_at__year=year)
            .annotate(month=TruncMonth("finished_at"))
            .values("month")
            .annotate(count=Count("id"))
        )
    }
    return _fill_year_months(year, rows, "count")


def pages_per_month_for_year(year: int) -> list[dict]:
    rows = {
        row["month"].strftime("%Y-%m"): row["pages"] or 0
        for row in (
            ReadingProgress.objects.filter(logged_on__year=year)
            .annotate(month=TruncMonth("logged_on"))
            .values("month")
            .annotate(pages=Sum("pages_read"))
        )
    }
    return _fill_year_months(year, rows, "pages")


def _finish_counts_for_month(year: int, month: int) -> dict[int, int]:
    return {
        row["finished_at"].day: row["count"]
        for row in (
            ReadingLog.objects.filter(
                finished_at__year=year,
                finished_at__month=month,
            )
            .values("finished_at")
            .annotate(count=Count("id"))
        )
    }


def _calendar_intensity(count: int, max_count: int) -> int:
    if count <= 0 or max_count <= 0:
        return 0
    ratio = count / max_count
    if ratio <= 0.25:
        return 1
    if ratio <= 0.5:
        return 2
    if ratio <= 0.75:
        return 3
    return 4


def _build_calendar_grid(
    year: int,
    month: int,
    counts: dict[int, int],
    max_count: int,
) -> dict:
    today = timezone.localdate()
    cal = calendar.Calendar(firstweekday=0)
    weeks = []
    for week in cal.monthdayscalendar(year, month):
        weeks.append(
            [
                {
                    "day": day,
                    "count": counts.get(day, 0) if day else 0,
                    "intensity": _calendar_intensity(counts.get(day, 0) if day else 0, max_count),
                    "is_today": day > 0 and year == today.year and month == today.month and day == today.day,
                }
                for day in week
            ]
        )
    return {
        "year": year,
        "month": month,
        "label": date(year, month, 1).strftime("%B %Y"),
        "weekday_labels": ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
        "weeks": weeks,
        "max_count": max_count,
    }


def finish_calendar_grid(year: int, month: int) -> dict:
    counts = _finish_counts_for_month(year, month)
    max_count = max(counts.values(), default=0)
    return _build_calendar_grid(year, month, counts, max_count)


def finish_calendar_strip(
    year: int,
    anchor_month: int,
    count: int = FINISH_CALENDAR_STRIP_MONTHS,
) -> dict:
    today = timezone.localdate()
    max_month = today.month if year == today.year else 12
    end_month = min(anchor_month, max_month)
    start_month = max(1, end_month - count + 1)
    month_range = range(start_month, end_month + 1)
    month_counts = {month: _finish_counts_for_month(year, month) for month in month_range}
    max_count = max(
        (day_count for counts in month_counts.values() for day_count in counts.values()),
        default=0,
    )
    calendars = [
        _build_calendar_grid(year, month, month_counts[month], max_count)
        for month in month_range
    ]
    if start_month == end_month:
        range_label = date(year, end_month, 1).strftime("%B %Y")
    else:
        start_label = date(year, start_month, 1).strftime("%B")
        end_label = date(year, end_month, 1).strftime("%B %Y")
        range_label = f"{start_label} – {end_label}"
    return {
        "calendars": calendars,
        "range_label": range_label,
        "anchor_month": end_month,
        "start_month": start_month,
    }


def books_finished_on(target_date: date) -> list[Book]:
    return list(
        Book.objects.filter(reading_log__finished_at=target_date)
        .prefetch_related("authors")
        .order_by("title")
    )


def parse_stats_year_month(
    year_param: str | None,
    month_param: str | None,
) -> tuple[int, int]:
    today = timezone.localdate()
    available = stats_available_years()
    default_year = today.year if today.year in available else available[-1]

    try:
        year = int(year_param) if year_param else default_year
    except (TypeError, ValueError):
        year = default_year
    if year not in available:
        year = default_year

    if year == today.year:
        default_month = today.month
        max_month = today.month
    else:
        max_month = 12
        default_month = max_month

    try:
        month = int(month_param) if month_param else default_month
    except (TypeError, ValueError):
        month = default_month
    month = max(1, min(max_month, month))
    return year, month


def parse_stats_period(
    period: str | None,
    start_param: str | None,
    end_param: str | None,
) -> tuple[date | None, date | None, str]:
    """Return (start, end, label) for stats filtering. (None, None) = all time."""
    today = timezone.localdate()
    period = (period or "all").lower()

    if period == "ytd":
        return date(today.year, 1, 1), today, f"{today.year} (YTD)"
    if period == "90d":
        return today - timedelta(days=89), today, "Last 90 days"
    if period == "custom" and start_param and end_param:
        try:
            start = date.fromisoformat(start_param)
            end = date.fromisoformat(end_param)
            if start <= end:
                return start, end, f"{start.isoformat()} – {end.isoformat()}"
        except ValueError:
            pass
    return None, None, "All time"


def rating_distribution(start: date | None = None, end: date | None = None) -> list[dict]:
    qs = Review.objects.filter(rating__isnull=False)
    if start and end:
        qs = qs.filter(
            book__reading_log__finished_at__gte=start,
            book__reading_log__finished_at__lte=end,
        )
    rows = qs.values("rating").annotate(count=Count("id")).order_by("rating")
    return [{"rating": row["rating"], "count": row["count"]} for row in rows]


def format_breakdown() -> list[dict]:
    labels = dict(BookFormat.choices)
    rows = Book.objects.values("format").annotate(count=Count("id")).order_by("-count")
    return [
        {"format": labels.get(row["format"], row["format"] or "Unknown"), "count": row["count"]}
        for row in rows
    ]


def dnf_stats() -> dict:
    dnf_logs = ReadingLog.objects.filter(status=ReadingStatus.ABANDONED).select_related("book")
    count = dnf_logs.count()
    if not count:
        return {"count": 0, "avg_progress_percent": None, "top_genres": []}

    progress_sum = 0
    progress_count = 0
    genre_counts: dict[str, int] = {}
    for log in dnf_logs.prefetch_related("book__genres"):
        if log.progress_percent is not None:
            progress_sum += log.progress_percent
            progress_count += 1
        for genre in log.book.genres.all():
            genre_counts[genre.name] = genre_counts.get(genre.name, 0) + 1
    top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    return {
        "count": count,
        "avg_progress_percent": round(progress_sum / progress_count, 1) if progress_count else None,
        "top_genres": [{"name": n, "count": c} for n, c in top_genres],
    }


def reading_speed_stats(start: date | None = None, end: date | None = None) -> dict:
    qs = ReadingProgress.objects.filter(pages_read__gt=0)
    if start and end:
        qs = qs.filter(logged_on__gte=start, logged_on__lte=end)
    totals = qs.aggregate(total_pages=Sum("pages_read"), days=Count("logged_on", distinct=True))
    total_pages = totals["total_pages"] or 0
    days = totals["days"] or 0
    return {
        "total_pages": total_pages,
        "active_days": days,
        "avg_pages_per_day": round(total_pages / days, 1) if days else None,
    }


def compute_stats(period_start: date | None = None, period_end: date | None = None):
    total_books = Book.objects.count()
    finished_count = ReadingLog.objects.filter(status=ReadingStatus.FINISHED).count()
    completion_rate = round(finished_count / total_books, 4) if total_books else 0.0

    books_by_shelf = [
        {
            "shelf_id": None,
            "slug": shelf.slug,
            "name": shelf.name,
            "count": shelf.book_count,
            "is_status_shelf": True,
        }
        for shelf in get_status_shelves()
    ] + [
        {
            "shelf_id": row["id"],
            "name": row["name"],
            "count": row["book_count"],
            "is_status_shelf": False,
        }
        for row in Shelf.objects.annotate(book_count=Count("bookshelf_items"))
        .order_by("sort_order", "name")
        .values("id", "name", "book_count")
    ]

    books_by_genre = _books_by_genre_for_display()

    books_by_status = [
        {"status": row["status"], "count": row["count"]}
        for row in ReadingLog.objects.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    ]

    monthly_reads = [
        {
            "month": row["month"].strftime("%Y-%m"),
            "count": row["count"],
        }
        for row in (
            ReadingLog.objects.filter(finished_at__isnull=False)
            .filter(**({"finished_at__gte": period_start} if period_start else {}))
            .filter(**({"finished_at__lte": period_end} if period_end else {}))
            .annotate(month=TruncMonth("finished_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
    ]

    progress_qs = ReadingProgress.objects.all()
    if period_start and period_end:
        progress_qs = progress_qs.filter(logged_on__gte=period_start, logged_on__lte=period_end)

    pages_read = progress_qs.aggregate(total=Sum("pages_read"))["total"] or 0

    activity_dates = set(progress_qs.values_list("logged_on", flat=True).distinct())
    reading_streak = _compute_reading_streak(activity_dates)

    goal = goal_progress()

    return {
        "total_books": total_books,
        "completion_rate": completion_rate,
        "books_by_shelf": books_by_shelf,
        "books_by_genre": books_by_genre,
        "books_by_status": books_by_status,
        "monthly_reads": monthly_reads,
        "pages_read": pages_read,
        "reading_streak": reading_streak,
        "reading_goal": goal,
        "pages_per_month": pages_per_month(),
        "reading_heatmap": reading_activity_heatmap(),
        "rating_distribution": rating_distribution(period_start, period_end),
        "format_breakdown": format_breakdown(),
        "dnf_stats": dnf_stats(),
        "reading_speed": reading_speed_stats(period_start, period_end),
    }
