from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from books.models import Book, Genre, ReadingLog, ReadingProgress, ReadingStatus, Shelf


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
            "shelf_id": row["id"],
            "name": row["name"],
            "count": row["book_count"],
        }
        for row in Shelf.objects.annotate(book_count=Count("bookshelf_items"))
        .order_by("sort_order", "name")
        .values("id", "name", "book_count")
    ]

    books_by_genre = [
        {
            "genre_id": row["id"],
            "name": row["name"],
            "count": row["book_count"],
        }
        for row in Genre.objects.annotate(book_count=Count("book_genres"))
        .order_by("name")
        .values("id", "name", "book_count")
    ]

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
