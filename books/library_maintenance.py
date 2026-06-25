from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from django.db import connection
from django.db.models import Count, Q

from books.covers import download_cover
from books.metadata import MetadataService, openlibrary_import_delay_seconds
from books.models import Book, GenreSource
from books.services import add_authors_to_book, add_genres_to_book

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]

_SCALAR_FIELDS = (
    "cover_url",
    "pages",
    "publisher",
    "published_year",
    "subtitle",
    "description",
    "openlibrary_work_id",
    "openlibrary_edition_key",
    "google_books_id",
)


@dataclass
class EnrichResult:
    updated_fields: list[str] = field(default_factory=list)


@dataclass
class BackfillResult:
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _has_isbn_filter() -> Q:
    return (Q(isbn_13__isnull=False) & ~Q(isbn_13="")) | (
        Q(isbn_10__isnull=False) & ~Q(isbn_10="")
    )


def _missing_cover_filter() -> Q:
    return Q(cover_image="") & (Q(cover_url__isnull=True) | Q(cover_url=""))


def _needs_cover_download_filter() -> Q:
    return Q(cover_image="") & ~Q(cover_url__isnull=True) & ~Q(cover_url="")


def _missing_metadata_filter() -> Q:
    return (
        _missing_cover_filter()
        | _needs_cover_download_filter()
        | Q(pages__isnull=True)
        | Q(author_count=0)
        | Q(genre_count=0)
        | Q(publisher__isnull=True)
        | Q(publisher="")
        | Q(published_year__isnull=True)
    )


def books_needing_metadata():
    return (
        Book.objects.annotate(
            author_count=Count("authors", distinct=True),
            genre_count=Count("genres", distinct=True),
        )
        .filter(_has_isbn_filter())
        .filter(_missing_metadata_filter())
        .order_by("created_at")
    )


def book_needs_metadata(book: Book) -> bool:
    if not (book.isbn_13 or book.isbn_10):
        return bool(book.cover_url and not book.cover_image)
    if not book.cover_image:
        return True
    if book.pages is None:
        return True
    if not book.authors.exists():
        return True
    if not book.genres.exists():
        return True
    if not book.publisher:
        return True
    if book.published_year is None:
        return True
    return False


def library_health_stats() -> dict[str, int]:
    base = Book.objects.annotate(
        author_count=Count("authors", distinct=True),
        genre_count=Count("genres", distinct=True),
    )
    return {
        "total_books": Book.objects.count(),
        "missing_cover": base.filter(Q(cover_image="")).count(),
        "missing_pages": base.filter(pages__isnull=True).count(),
        "no_authors": base.filter(author_count=0).count(),
        "no_genres": base.filter(genre_count=0).count(),
        "no_isbn": base.filter(
            (Q(isbn_13__isnull=True) | Q(isbn_13=""))
            & (Q(isbn_10__isnull=True) | Q(isbn_10=""))
        ).count(),
        "needing_metadata": books_needing_metadata().count(),
    }


def _is_empty(value) -> bool:
    return value is None or value == ""


def enrich_book_from_metadata(book: Book, metadata: dict) -> EnrichResult:
    result = EnrichResult()
    if not metadata:
        return result

    for field_name in _SCALAR_FIELDS:
        if field_name in metadata and metadata[field_name] and _is_empty(getattr(book, field_name)):
            setattr(book, field_name, metadata[field_name])
            result.updated_fields.append(field_name)

    if metadata.get("authors") and not book.authors.exists():
        add_authors_to_book(book, metadata["authors"])
        result.updated_fields.append("authors")

    if metadata.get("genres") and not book.genres.exists():
        add_genres_to_book(book, metadata["genres"], source=GenreSource.OPEN_LIBRARY)
        result.updated_fields.append("genres")

    if result.updated_fields:
        scalar_updated = any(f in result.updated_fields for f in _SCALAR_FIELDS)
        if scalar_updated:
            book.save()

    if book.cover_url and (not book.cover_image or "cover_url" in result.updated_fields):
        force = "cover_url" in result.updated_fields
        if download_cover(book, force=force):
            result.updated_fields.append("cover_image")

    return result


def _lookup_isbn_for_book(book: Book, service: MetadataService) -> tuple[dict, str | None]:
    isbn = book.isbn_13 or book.isbn_10
    if not isbn:
        return {}, None
    try:
        return service.lookup_isbn(isbn, import_context=True), None
    except Exception as exc:
        logger.warning("Metadata lookup failed for book %s: %s", book.pk, exc)
        return {}, f"metadata lookup failed: {exc}"


def _sleep_after_lookup() -> None:
    delay = openlibrary_import_delay_seconds()
    if delay > 0:
        time.sleep(delay)


def refresh_book_metadata(book: Book, *, service: MetadataService | None = None) -> EnrichResult:
    isbn = book.isbn_13 or book.isbn_10
    if not isbn:
        return EnrichResult()

    svc = service or MetadataService()
    try:
        metadata = svc.lookup_isbn(isbn, import_context=True)
    except Exception as exc:
        logger.warning("Metadata lookup failed for book %s: %s", book.pk, exc)
        return EnrichResult()
    finally:
        _sleep_after_lookup()

    return enrich_book_from_metadata(book, metadata)


def backfill_metadata(
    book_ids: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
) -> BackfillResult:
    result = BackfillResult()
    total = len(book_ids)
    service = MetadataService()

    for index, book_id in enumerate(book_ids, start=1):
        if progress_callback:
            progress_callback(index - 1, total)

        try:
            book = Book.objects.get(pk=book_id)
        except Book.DoesNotExist:
            result.failed += 1
            result.errors.append(f"{book_id}: book not found")
            continue

        if not book_needs_metadata(book):
            result.skipped += 1
            continue

        metadata, lookup_error = _lookup_isbn_for_book(book, service)
        _sleep_after_lookup()

        enrich_result = enrich_book_from_metadata(book, metadata)
        if not enrich_result.updated_fields and book.cover_url and not book.cover_image:
            if download_cover(book):
                enrich_result.updated_fields.append("cover_image")
        if enrich_result.updated_fields:
            result.updated += 1
        else:
            result.skipped += 1
            if lookup_error:
                result.errors.append(f"{book.title}: {lookup_error}")
            elif metadata:
                result.errors.append(f"{book.title}: lookup returned data but no empty fields to fill")
            else:
                result.errors.append(f"{book.title}: no metadata found for ISBN")

    if progress_callback:
        progress_callback(total, total)

    return result


def clear_metadata_cache() -> int:
    from django.core.cache import caches

    cache_backend = caches["default"]
    backend_name = cache_backend.__class__.__name__

    if backend_name == "DatabaseCache":
        table = cache_backend._table
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {table} WHERE cache_key LIKE %s",
                ["%metadata:isbn:%"],
            )
            return cursor.rowcount

    cache_backend.clear()
    return 0
