from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from django.db import connection
from django.db.models import Count, Q
from django.utils import timezone

from books.covers import (
    clear_invalid_cover,
    download_cover,
    has_valid_cover,
    is_openlibrary_cover_url,
    stored_cover_is_valid,
)
from books.metadata import MetadataService, openlibrary_import_delay_seconds
from books.metadata_match import (
    apply_lookup_result,
    create_or_update_proposal,
    lookup_for_book,
)
from books.models import Book, GenreSource, MetadataMatchProposal, MetadataMatchProposalStatus
from books.services import add_authors_to_book, add_genres_to_book, attach_authors_to_book

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
    "wikidata_id",
    "hardcover_edition_id",
)

_REFRESH_SCALAR_FIELDS = _SCALAR_FIELDS + ("isbn_13", "isbn_10")


@dataclass
class EnrichResult:
    updated_fields: list[str] = field(default_factory=list)


@dataclass
class BackfillResult:
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    pending_review: int = 0
    errors: list[str] = field(default_factory=list)


def _has_isbn_filter() -> Q:
    return (Q(isbn_13__isnull=False) & ~Q(isbn_13="")) | (
        Q(isbn_10__isnull=False) & ~Q(isbn_10="")
    )


def _has_title_and_author_filter() -> Q:
    return Q(author_count__gt=0)


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
        | Q(description__isnull=True)
        | Q(description="")
        | Q(subtitle__isnull=True)
        | Q(subtitle="")
        | Q(series__isnull=True)
        | (
            (Q(isbn_13__isnull=True) | Q(isbn_13=""))
            & (Q(isbn_10__isnull=True) | Q(isbn_10=""))
        )
    )


def books_needing_metadata():
    return (
        Book.objects.annotate(
            author_count=Count("authors", distinct=True),
            genre_count=Count("genres", distinct=True),
        )
        .filter(
            _has_isbn_filter() | _has_title_and_author_filter(),
        )
        .filter(_missing_metadata_filter())
        .order_by("created_at")
    )


def book_needs_metadata(book: Book) -> bool:
    has_isbn = bool(book.isbn_13 or book.isbn_10)
    has_authors = book.authors.exists()
    if not has_isbn and not has_authors:
        return not has_valid_cover(book)
    if not has_valid_cover(book):
        return True
    if book.pages is None:
        return True
    if not has_authors:
        return True
    if not book.genres.exists():
        return True
    if not book.publisher:
        return True
    if book.published_year is None:
        return True
    if not book.description:
        return True
    if not book.subtitle:
        return True
    if book.series_id is None:
        return True
    if not has_isbn:
        return True
    return False


def metadata_missing_fields(book: Book) -> list[str]:
    """Human-readable list of bibliographic gaps for coverage UI."""
    missing: list[str] = []
    if not has_valid_cover(book):
        missing.append("cover")
    if book.pages is None:
        missing.append("pages")
    if not book.authors.exists():
        missing.append("authors")
    if not book.genres.exists():
        missing.append("genres")
    if not book.publisher:
        missing.append("publisher")
    if book.published_year is None:
        missing.append("published year")
    if not book.description:
        missing.append("description")
    if not book.subtitle:
        missing.append("subtitle")
    if book.series_id is None:
        missing.append("series")
    if not (book.isbn_13 or book.isbn_10):
        missing.append("ISBN")
    return missing


def _count_missing_covers(queryset) -> int:
    no_cover = queryset.filter(_missing_cover_filter()).count()
    invalid_local = sum(
        1
        for book in queryset.filter(~Q(cover_image="")).iterator()
        if not stored_cover_is_valid(book)
    )
    return no_cover + invalid_local


def apply_health_missing_filter(queryset, missing: str):
    """Filter books by library health gap (used from books list deep links)."""
    from django.db.models import Count

    qs = queryset.annotate(
        author_count=Count("authors", distinct=True),
        genre_count=Count("genres", distinct=True),
    )
    if missing == "cover":
        return qs.filter(_missing_cover_filter())
    if missing == "pages":
        return qs.filter(pages__isnull=True)
    if missing == "authors":
        return qs.filter(author_count=0)
    if missing == "genres":
        return qs.filter(genre_count=0)
    if missing == "isbn":
        return qs.filter(
            (Q(isbn_13__isnull=True) | Q(isbn_13=""))
            & (Q(isbn_10__isnull=True) | Q(isbn_10=""))
        )
    if missing == "metadata":
        return qs.filter(pk__in=books_needing_metadata().values_list("pk", flat=True))
    return qs


def library_health_stats() -> dict[str, int]:
    base = Book.objects.annotate(
        author_count=Count("authors", distinct=True),
        genre_count=Count("genres", distinct=True),
    )
    return {
        "total_books": Book.objects.count(),
        "missing_cover": _count_missing_covers(base),
        "missing_pages": base.filter(pages__isnull=True).count(),
        "no_authors": base.filter(author_count=0).count(),
        "no_genres": base.filter(genre_count=0).count(),
        "no_isbn": base.filter(
            (Q(isbn_13__isnull=True) | Q(isbn_13=""))
            & (Q(isbn_10__isnull=True) | Q(isbn_10=""))
        ).count(),
        "needing_metadata": books_needing_metadata().count(),
        "pending_metadata_matches": MetadataMatchProposal.objects.filter(
            status=MetadataMatchProposalStatus.PENDING,
        ).count(),
    }


def _is_empty(value) -> bool:
    return value is None or value == ""


def enrich_book_from_metadata(book: Book, metadata: dict, *, mode: str = "fill") -> EnrichResult:
    result = EnrichResult()
    if not metadata:
        return result

    locked = set(book.metadata_locked_fields or [])
    scalar_fields = _REFRESH_SCALAR_FIELDS if mode == "refresh" else _SCALAR_FIELDS

    for field_name in scalar_fields:
        if field_name in locked:
            continue
        if field_name not in metadata or not metadata[field_name]:
            continue
        if mode == "refresh" or _is_empty(getattr(book, field_name)):
            setattr(book, field_name, metadata[field_name])
            result.updated_fields.append(field_name)

    if mode == "fill":
        for isbn_field in ("isbn_13", "isbn_10"):
            if isbn_field in locked:
                continue
            if metadata.get(isbn_field) and _is_empty(getattr(book, isbn_field)):
                setattr(book, isbn_field, metadata[isbn_field])
                if isbn_field not in result.updated_fields:
                    result.updated_fields.append(isbn_field)

    if metadata.get("authors") and "authors" not in locked:
        if mode == "refresh":
            attach_authors_to_book(book, metadata["authors"])
            result.updated_fields.append("authors")
        elif not book.authors.exists():
            add_authors_to_book(book, metadata["authors"])
            result.updated_fields.append("authors")

    if metadata.get("genres") and "genres" not in locked:
        if mode == "refresh":
            book.genres.clear()
            add_genres_to_book(book, metadata["genres"], source=GenreSource.OPEN_LIBRARY)
            result.updated_fields.append("genres")
        elif not book.genres.exists():
            add_genres_to_book(book, metadata["genres"], source=GenreSource.OPEN_LIBRARY)
            result.updated_fields.append("genres")

    series_name = metadata.get("series_name")
    if series_name and (mode == "refresh" or book.series_id is None):
        from books.services import get_or_create_series

        book.series = get_or_create_series(series_name)
        if metadata.get("series_position") is not None:
            book.series_position = metadata["series_position"]
        result.updated_fields.append("series")

    if metadata.get("source_summary"):
        book.metadata_source_summary = metadata["source_summary"]
        if "metadata_source_summary" not in result.updated_fields:
            result.updated_fields.append("metadata_source_summary")

    if result.updated_fields:
        book.last_metadata_refresh_at = timezone.now()
        if "last_metadata_refresh_at" not in result.updated_fields:
            result.updated_fields.append("last_metadata_refresh_at")
        update_fields = [
            f for f in result.updated_fields if f not in ("authors", "genres", "cover_image")
        ]
        if "series" in update_fields:
            update_fields = [f for f in update_fields if f != "series"]
            update_fields.extend(["series", "series_position"])
        if update_fields:
            book.save(update_fields=update_fields)

    clear_invalid_cover(book)
    if book.cover_url and (
        not stored_cover_is_valid(book) or "cover_url" in result.updated_fields
    ):
        force = "cover_url" in result.updated_fields
        if download_cover(book, force=force):
            result.updated_fields.append("cover_image")
        elif is_openlibrary_cover_url(book.cover_url):
            book.cover_url = None
            book.save(update_fields=["cover_url"])

    return result


def _sleep_after_lookup() -> None:
    delay = openlibrary_import_delay_seconds()
    if delay > 0:
        time.sleep(delay)


def refresh_book_metadata(book: Book, *, service: MetadataService | None = None) -> EnrichResult:
    del service
    try:
        lookup = lookup_for_book(book, import_context=False)
    except Exception as exc:
        logger.warning("Metadata lookup failed for book %s: %s", book.pk, exc)
        return EnrichResult()
    finally:
        _sleep_after_lookup()

    return apply_lookup_result(book, lookup, mode="refresh")


def backfill_metadata(
    book_ids: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> BackfillResult:
    result = BackfillResult()
    total = len(book_ids)
    remaining_ids = list(book_ids)

    def _report_progress(done: int) -> None:
        if progress_callback:
            progress_callback(done, total)

    from books.metadata_isbndb import isbndb_enabled, lookup_isbns_batch

    if isbndb_enabled() and remaining_ids:
        service = MetadataService()
        isbn_book_map: dict[str, Book] = {}
        for book_id in remaining_ids:
            try:
                book = Book.objects.get(pk=book_id)
            except Book.DoesNotExist:
                continue
            if not book_needs_metadata(book):
                continue
            isbn = book.isbn_13
            if isbn:
                isbn_book_map[isbn] = book

        isbn_list = list(isbn_book_map.keys())
        for offset in range(0, len(isbn_list), 100):
            if should_stop and should_stop():
                break
            batch = isbn_list[offset : offset + 100]
            batch_meta = lookup_isbns_batch(
                batch,
                service.session,
                post_fn=service._post_isbndb,
                import_context=True,
            )
            for isbn, meta in batch_meta.items():
                book = isbn_book_map.get(isbn)
                if not book or not meta:
                    continue
                enrich_result = enrich_book_from_metadata(book, meta, mode="fill")
                if enrich_result.updated_fields:
                    result.updated += 1
                    if book.cover_url and not book.cover_image:
                        download_cover(book)
                else:
                    result.skipped += 1
            _sleep_after_lookup()

    for index, book_id in enumerate(book_ids, start=1):
        if should_stop and should_stop():
            break

        try:
            book = Book.objects.get(pk=book_id)
        except Book.DoesNotExist:
            result.failed += 1
            result.errors.append(f"{book_id}: book not found")
            _report_progress(index)
            continue

        if not book_needs_metadata(book):
            result.skipped += 1
            _report_progress(index)
            continue

        if should_stop and should_stop():
            break

        try:
            lookup = lookup_for_book(book, import_context=True)
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"{book.title}: metadata lookup failed: {exc}")
        else:
            if lookup.auto_apply and lookup.metadata:
                enrich_result = apply_lookup_result(book, lookup, mode="fill")
                if not enrich_result.updated_fields and book.cover_url and not book.cover_image:
                    if should_stop and should_stop():
                        break
                    if download_cover(book):
                        enrich_result.updated_fields.append("cover_image")
                if enrich_result.updated_fields:
                    result.updated += 1
                else:
                    result.skipped += 1
                    if lookup.metadata:
                        result.errors.append(
                            f"{book.title}: lookup returned data but no empty fields to fill"
                        )
                    else:
                        result.errors.append(f"{book.title}: no metadata found")
            elif lookup.needs_review:
                create_or_update_proposal(book, lookup)
                result.pending_review += 1
                result.skipped += 1
                result.errors.append(
                    f"{book.title}: pending metadata review (score {lookup.score:.2f})"
                )
            else:
                result.skipped += 1
                if lookup.metadata:
                    result.errors.append(
                        f"{book.title}: lookup returned data but no empty fields to fill"
                    )
                else:
                    result.errors.append(f"{book.title}: no metadata found")
        finally:
            _sleep_after_lookup()

        _report_progress(index)

        if should_stop and should_stop():
            break

    return result


def clear_metadata_cache() -> int:
    from django.core.cache import caches

    cache_backend = caches["default"]
    backend_name = cache_backend.__class__.__name__

    if backend_name == "DatabaseCache":
        table = cache_backend._table
        with connection.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {table} WHERE cache_key LIKE %s OR cache_key LIKE %s"
                f" OR cache_key LIKE %s OR cache_key LIKE %s",
                [
                    "%metadata:isbn:%",
                    "%metadata:wikidata:%",
                    "%metadata:search-search:%",
                    "%metadata:wikidata-search:%",
                ],
            )
            return cursor.rowcount

    cache_backend.clear()
    return 0


@dataclass
class DuplicateGroup:
    match_type: str
    match_key: str
    books: list[Book] = field(default_factory=list)


def find_duplicate_groups() -> list[DuplicateGroup]:
    from collections import defaultdict

    from books.import_export import _book_dedup_key

    groups: list[DuplicateGroup] = []
    grouped_book_ids: set = set()

    for field_name in ("isbn_13", "isbn_10"):
        values = (
            Book.objects.exclude(**{f"{field_name}__isnull": True})
            .exclude(**{field_name: ""})
            .values(field_name)
            .annotate(count=Count("id"))
            .filter(count__gt=1)
        )
        for row in values:
            isbn_value = row[field_name]
            books = list(
                Book.objects.filter(**{field_name: isbn_value})
                .prefetch_related("authors")
                .order_by("created_at")
            )
            book_ids = {book.pk for book in books}
            if book_ids & grouped_book_ids:
                continue
            grouped_book_ids |= book_ids
            groups.append(
                DuplicateGroup(
                    match_type=field_name,
                    match_key=isbn_value,
                    books=books,
                )
            )

    title_author_map: dict[str, list[Book]] = defaultdict(list)
    for book in Book.objects.prefetch_related("authors").order_by("created_at"):
        if book.pk in grouped_book_ids:
            continue
        primary = book.authors.order_by("book_authors__position").first()
        if not primary:
            continue
        key = _book_dedup_key(book.title, primary.name)
        if not key or key == "|":
            continue
        title_author_map[key].append(book)

    for key, books in title_author_map.items():
        if len(books) < 2:
            continue
        grouped_book_ids |= {book.pk for book in books}
        groups.append(
            DuplicateGroup(
                match_type="title_author",
                match_key=key,
                books=books,
            )
        )

    return groups


def _fill_empty_book_fields(keeper: Book, source: Book) -> None:
    scalar_fields = (
        "subtitle",
        "isbn_13",
        "isbn_10",
        "pages",
        "published_year",
        "published_date",
        "publisher",
        "description",
        "cover_url",
        "openlibrary_work_id",
        "openlibrary_edition_key",
        "google_books_id",
        "language",
    )
    updated = False
    for field_name in scalar_fields:
        if _is_empty(getattr(keeper, field_name)) and not _is_empty(getattr(source, field_name)):
            setattr(keeper, field_name, getattr(source, field_name))
            updated = True
    if updated:
        keeper.save()


def _merge_reading_logs(keeper: Book, source: Book) -> None:
    from books.services import create_reading_log_for_book

    keeper_log = getattr(keeper, "reading_log", None)
    if keeper_log is None:
        keeper_log = create_reading_log_for_book(keeper)
    source_log = getattr(source, "reading_log", None)
    if source_log is None:
        return

    status_rank = {
        "not_started": 0,
        "reading": 2,
        "paused": 1,
        "finished": 3,
        "abandoned": 1,
    }
    if status_rank.get(source_log.status, 0) > status_rank.get(keeper_log.status, 0):
        keeper_log.status = source_log.status
    for field_name in (
        "current_page",
        "progress_percent",
        "total_pages",
        "read_count",
        "started_at",
        "finished_at",
    ):
        source_value = getattr(source_log, field_name)
        keeper_value = getattr(keeper_log, field_name)
        if keeper_value in (None, "", 0) and source_value not in (None, "", 0):
            setattr(keeper_log, field_name, source_value)
    keeper_log.save()

    from books.models import ReadingProgress

    ReadingProgress.objects.filter(book=source).update(book=keeper, reading_log=keeper_log)


def merge_books(keeper_id, merge_ids: list) -> Book:
    from django.db import transaction

    from books.models import (
        BookshelfItem,
        MetadataMatchProposal,
        Quote,
        Review,
    )

    keeper = Book.objects.get(pk=keeper_id)
    merge_ids = [str(book_id) for book_id in merge_ids if str(book_id) != str(keeper_id)]

    with transaction.atomic():
        for merge_id in merge_ids:
            source = Book.objects.get(pk=merge_id)

            for author_link in list(source.book_authors.all()):
                if keeper.authors.filter(pk=author_link.author_id).exists():
                    author_link.delete()
                else:
                    author_link.book = keeper
                    author_link.save(update_fields=["book"])

            for genre_link in list(source.book_genres.all()):
                if keeper.genres.filter(pk=genre_link.genre_id).exists():
                    genre_link.delete()
                else:
                    genre_link.book = keeper
                    genre_link.save(update_fields=["book"])

            for item in BookshelfItem.objects.filter(book=source):
                BookshelfItem.objects.get_or_create(book=keeper, shelf=item.shelf)

            try:
                source_review = source.review
            except Review.DoesNotExist:
                source_review = None
            try:
                keeper.review
            except Review.DoesNotExist:
                if source_review is not None:
                    source_review.book = keeper
                    source_review.save(update_fields=["book"])
            else:
                if source_review is not None:
                    source_review.delete()

            _merge_reading_logs(keeper, source)
            Quote.objects.filter(book=source).update(book=keeper)
            MetadataMatchProposal.objects.filter(book=source).delete()
            _fill_empty_book_fields(keeper, source)

            source.deleted_at = timezone.now()
            source.save(update_fields=["deleted_at"])

    keeper.refresh_from_db()
    return keeper
