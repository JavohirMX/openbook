from __future__ import annotations

from books.models import Book, ReadingLog, ReadingStatus


from books.covers import cover_served_url


def currently_reading_books(limit: int = 10, *, request=None) -> list[dict]:
    logs = (
        ReadingLog.objects.filter(status=ReadingStatus.READING)
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("-updated_at")[:limit]
    )
    return [_serialize_embed_book(log.book, log, request=request) for log in logs]


def recently_finished_books(limit: int = 10, *, request=None) -> list[dict]:
    logs = (
        ReadingLog.objects.filter(status=ReadingStatus.FINISHED, finished_at__isnull=False)
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("-finished_at")[:limit]
    )
    return [_serialize_embed_book(log.book, log, request=request) for log in logs]


def _serialize_embed_book(book: Book, log: ReadingLog | None = None, *, request=None) -> dict:
    authors = [a.name for a in book.authors.all()]
    payload = {
        "id": str(book.pk),
        "title": book.title,
        "authors": authors,
        "cover_url": cover_served_url(book, request),
        "url": f"/books/{book.pk}/",
    }
    if log:
        payload["status"] = log.status
        payload["progress_percent"] = log.progress_percent
        if log.finished_at:
            payload["finished_at"] = log.finished_at.isoformat()
    return payload


def embed_payload(kind: str = "currently_reading", *, request=None) -> dict:
    if kind == "recently_finished":
        books = recently_finished_books(request=request)
        title = "Recently finished"
    else:
        books = currently_reading_books(request=request)
        title = "Currently reading"
    return {"title": title, "books": books}
