from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from books.models import Book, Genre, ReadingLog, ReadingProgress, ReadingStatus, Shelf

GENRE_STATS_TOP_N = 12


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


def compute_stats():
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
            .annotate(month=TruncMonth("finished_at"))
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )
    ]

    pages_read = (
        ReadingProgress.objects.aggregate(total=Sum("pages_read"))["total"] or 0
    )

    activity_dates = set(
        ReadingProgress.objects.values_list("logged_on", flat=True).distinct()
    )
    reading_streak = _compute_reading_streak(activity_dates)

    return {
        "total_books": total_books,
        "completion_rate": completion_rate,
        "books_by_shelf": books_by_shelf,
        "books_by_genre": books_by_genre,
        "books_by_status": books_by_status,
        "monthly_reads": monthly_reads,
        "pages_read": pages_read,
        "reading_streak": reading_streak,
    }
