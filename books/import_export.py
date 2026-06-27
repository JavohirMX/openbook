import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time
from decimal import Decimal, InvalidOperation

from collections.abc import Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from books.covers import download_cover
from books.genre_normalize import METADATA_GENRE_LIMIT
from books.isbn import normalize_and_validate
from books.metadata import MetadataService
from books.models import (
    Author,
    Book,
    BookAuthor,
    BookshelfItem,
    Genre,
    GenreSource,
    ReadingLog,
    ReadingStatus,
    Review,
    Shelf,
)
from books.reading_service import update_reading_log
from books.services import (
    attach_authors_to_book,
    attach_genres_to_book,
    create_reading_log_for_book,
    get_or_create_genres,
    get_or_create_series,
)


EXCLUSIVE_SHELVES = {"read", "currently-reading", "to-read"}
STATUS_MAP = {
    "read": ReadingStatus.FINISHED,
    "currently-reading": ReadingStatus.READING,
    "to-read": ReadingStatus.NOT_STARTED,
}


@dataclass
class ImportResult:
    added: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _normalize_key(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    for ch in ".,;:'\"()-":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def _book_dedup_key(title: str, author: str) -> str:
    return f"{_normalize_key(title)}|{_normalize_key(author)}"


def _find_duplicate(isbn_13=None, isbn_10=None, title=None, author=None):
    if isbn_13:
        book = Book.all_objects.filter(isbn_13=isbn_13).first()
        if book:
            return book
    if isbn_10:
        book = Book.all_objects.filter(isbn_10=isbn_10).first()
        if book:
            return book
    if title and author:
        key = _book_dedup_key(title, author)
        for book in Book.all_objects.prefetch_related("authors"):
            primary = book.authors.order_by("book_authors__position").first()
            if primary and _book_dedup_key(book.title, primary.name) == key:
                return book
    return None


def _create_book_from_data(data: dict, metadata: dict | None = None) -> Book:
    meta = metadata or {}
    title = data.get("title") or meta.get("title")
    if not title:
        raise ValueError("Title is required")

    isbn_13 = data.get("isbn_13")
    isbn_10 = data.get("isbn_10")
    if data.get("isbn"):
        n13, n10, _ = normalize_and_validate(raw=data["isbn"])
        isbn_13 = isbn_13 or n13
        isbn_10 = isbn_10 or n10

    authors = data.get("authors") or meta.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(",") if a.strip()]
    if not authors and data.get("author"):
        authors = [data["author"]]
    primary_author = authors[0] if authors else data.get("author", "")

    dup = _find_duplicate(isbn_13, isbn_10, title, primary_author)
    if dup:
        raise ValueError(f"duplicate:{dup.id}")

    book = Book.objects.create(
        title=title,
        subtitle=data.get("subtitle") or meta.get("subtitle"),
        isbn_13=isbn_13,
        isbn_10=isbn_10,
        pages=data.get("pages") or meta.get("pages"),
        published_year=data.get("published_year") or meta.get("published_year"),
        publisher=data.get("publisher") or meta.get("publisher"),
        description=data.get("description") or meta.get("description"),
        cover_url=data.get("cover_url") or meta.get("cover_url"),
        language=data.get("language") or meta.get("language") or "en",
        openlibrary_work_id=meta.get("openlibrary_work_id"),
        openlibrary_edition_key=meta.get("openlibrary_edition_key"),
        google_books_id=meta.get("google_books_id"),
        wikidata_id=meta.get("wikidata_id"),
        hardcover_edition_id=meta.get("hardcover_edition_id"),
        metadata_source_summary=meta.get("source_summary"),
    )

    if authors:
        attach_authors_to_book(book, authors)
    elif data.get("author"):
        attach_authors_to_book(book, [data["author"]])

    genre_names = data.get("genres") or meta.get("genres") or []
    if genre_names:
        genres = get_or_create_genres(genre_names[:METADATA_GENRE_LIMIT], GenreSource.OPEN_LIBRARY)
        attach_genres_to_book(book, genres)

    series_name = data.get("series_name")
    if series_name:
        book.series = get_or_create_series(series_name)
        book.series_position = data.get("series_position")
        book.save(update_fields=["series", "series_position"])

    create_reading_log_for_book(book)

    if book.cover_url:
        download_cover(book)

    status = data.get("status")
    if status:
        log = book.reading_log
        update_reading_log(log, {"status": status})

    _apply_goodreads_import_dates(book, data)

    rating = data.get("rating")
    if rating:
        Review.objects.update_or_create(
            book=book,
            defaults={"rating": rating if rating else None},
        )

    return book


ProgressCallback = Callable[[int, int], None]
ShouldStop = Callable[[], bool] | None

logger = logging.getLogger(__name__)


def _import_lookup_delay() -> float:
    from books.metadata import openlibrary_import_delay_seconds

    return openlibrary_import_delay_seconds()


def _sleep_after_import_lookup() -> None:
    delay = _import_lookup_delay()
    if delay > 0:
        time.sleep(delay)


def _lookup_metadata_for_import(service: MetadataService, parsed: dict) -> dict:
    from books.metadata_match import lookup_metadata_for_import

    try:
        return lookup_metadata_for_import(parsed, service=service, import_context=True)
    except Exception:
        isbn = parsed.get("isbn_13") or parsed.get("isbn_10")
        logger.info("Metadata enrichment skipped for %s", isbn or parsed.get("title"))
        return {}
    finally:
        _sleep_after_import_lookup()


def _should_enrich_goodreads_row(parsed: dict) -> bool:
    if not getattr(settings, "IMPORT_GOODREADS_ENRICH_METADATA", False):
        return False
    if parsed.get("isbn_13") or parsed.get("isbn_10"):
        return True
    return bool(parsed.get("title") and parsed.get("author"))


def import_isbns(
    isbn_list: list[str],
    progress_callback: ProgressCallback | None = None,
) -> ImportResult:
    result = ImportResult()
    service = MetadataService()
    items = [raw.strip() for raw in isbn_list if raw.strip()]
    total = len(items)

    for index, isbn in enumerate(items, start=1):
        try:
            with transaction.atomic():
                isbn_13, isbn_10, _ = normalize_and_validate(raw=isbn)
                if _find_duplicate(isbn_13, isbn_10):
                    result.skipped += 1
                    continue
                from books.metadata_match import lookup_metadata_for_import

                meta = lookup_metadata_for_import(
                    {"isbn_13": isbn_13, "isbn_10": isbn_10},
                    service=service,
                    import_context=True,
                )
                _sleep_after_import_lookup()
                if not meta.get("title"):
                    result.failed += 1
                    result.errors.append(f"{isbn}: no metadata found")
                    continue
                _create_book_from_data({"isbn": isbn}, meta)
                result.added += 1
        except ValueError as exc:
            if str(exc).startswith("duplicate:"):
                result.skipped += 1
            else:
                result.failed += 1
                result.errors.append(f"{isbn}: {exc}")
        except Exception as exc:
            result.failed += 1
            result.errors.append(f"{isbn}: {exc}")
        finally:
            if progress_callback:
                progress_callback(index, total)

    return result


def _parse_goodreads_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _apply_goodreads_import_dates(book: Book, data: dict) -> None:
    date_added = data.get("date_added")
    if date_added:
        created_at = datetime.combine(date_added, dt_time(hour=12))
        if settings.USE_TZ:
            created_at = timezone.make_aware(created_at, timezone.get_current_timezone())
        Book.objects.filter(pk=book.pk).update(created_at=created_at)

    date_read = data.get("date_read")
    if not date_read:
        return
    try:
        log = book.reading_log
    except ReadingLog.DoesNotExist:
        return
    if log.status == ReadingStatus.FINISHED:
        log.finished_at = date_read
        if not log.started_at:
            log.started_at = date_read
        if log.read_count < 1:
            log.read_count = 1
        log.save(update_fields=["finished_at", "started_at", "read_count"])


def _parse_goodreads_isbn(value: str) -> str | None:
    if not value:
        return None
    value = value.strip()
    if value.startswith('="') and value.endswith('"'):
        value = value[2:-1]
    else:
        value = value.strip('"')
    value = value.strip()
    if not value:
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", value)
    if len(cleaned) == 13 and cleaned.isdigit():
        return cleaned
    if len(cleaned) == 10:
        return cleaned.upper()
    return None


def _parse_series_position(value: str) -> Decimal | None:
    value = (value or "").strip().lstrip("#")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _parse_goodreads_series(row: dict) -> tuple[str | None, Decimal | None]:
    series_name = None
    for key in ("Series", "series"):
        if key in row and row[key]:
            series_name = row[key].strip() or None
            if series_name:
                break

    position = None
    for key in ("#", "# In Series", "Series Position", "Book Num", "Book Number"):
        if key in row and row[key]:
            position = _parse_series_position(row[key])
            if position is not None:
                break
    return series_name, position


def _parse_goodreads_row(row: dict) -> dict:
    title = row.get("Title", "").strip()
    author = row.get("Author", "").strip()
    isbn_13 = _parse_goodreads_isbn(row.get("ISBN13", ""))
    isbn_10 = _parse_goodreads_isbn(row.get("ISBN", ""))

    pages = row.get("Number of Pages", "").strip()
    pages_int = int(pages) if pages.isdigit() else None

    year = row.get("Year Published", "") or row.get("Original Publication Year", "")
    year_int = int(year) if str(year).strip().isdigit() else None

    rating_raw = row.get("My Rating", "0").strip()
    rating = int(rating_raw) if rating_raw.isdigit() and int(rating_raw) > 0 else None

    exclusive = row.get("Exclusive Shelf", "").strip().lower()
    status = STATUS_MAP.get(exclusive)

    shelves_raw = row.get("Bookshelves", "")
    shelf_names = [
        s.strip()
        for s in shelves_raw.split(",")
        if s.strip() and s.strip().lower() not in EXCLUSIVE_SHELVES
    ]

    additional_raw = row.get("Additional Authors", "").strip()
    additional_authors = [a.strip() for a in additional_raw.split(",") if a.strip()]
    authors = [author] if author else []
    authors.extend(a for a in additional_authors if a not in authors)

    series_name, series_position = _parse_goodreads_series(row)

    return {
        "title": title,
        "author": author,
        "authors": authors,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "pages": pages_int,
        "published_year": year_int,
        "publisher": row.get("Publisher", "").strip() or None,
        "rating": rating,
        "status": status,
        "review_text": row.get("My Review", "").strip() or None,
        "shelf_names": shelf_names,
        "date_read": _parse_goodreads_date(row.get("Date Read", "")),
        "date_added": _parse_goodreads_date(row.get("Date Added", "")),
        "series_name": series_name,
        "series_position": series_position,
    }


def _serialize_preview_row(parsed: dict) -> dict:
    row = dict(parsed)
    status = row.get("status")
    if status is not None and hasattr(status, "value"):
        row["status"] = status.value
    status_value = row.get("status")
    if status_value:
        row["status_display"] = dict(ReadingStatus.choices).get(status_value, status_value)
    for key in ("date_read", "date_added"):
        value = row.get(key)
        if isinstance(value, date):
            row[key] = value.isoformat()
    return row


def preview_goodreads_csv(file) -> list[dict]:
    import csv
    import io

    content = file.read()
    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    preview = []
    for row in reader:
        parsed = _parse_goodreads_row(row)
        if not parsed["title"]:
            continue
        dup = _find_duplicate(
            parsed.get("isbn_13"),
            parsed.get("isbn_10"),
            parsed["title"],
            parsed.get("author"),
        )
        parsed["is_duplicate"] = dup is not None
        parsed["duplicate_id"] = str(dup.id) if dup else None
        preview.append(_serialize_preview_row(parsed))
    return preview


def _read_csv_rows(file) -> list[dict]:
    import csv
    import io

    if hasattr(file, "read"):
        content = file.read()
        if hasattr(file, "seek"):
            file.seek(0)
    else:
        with open(file, "rb") as handle:
            content = handle.read()

    if isinstance(content, bytes):
        content = content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(content)))


def import_goodreads_csv(
    file,
    progress_callback: ProgressCallback | None = None,
    should_stop: ShouldStop = None,
) -> ImportResult:
    result = ImportResult()
    service = MetadataService()
    all_rows = _read_csv_rows(file)
    total = len(all_rows)

    for index, row in enumerate(all_rows, start=1):
        parsed = _parse_goodreads_row(row)
        if not parsed["title"]:
            result.failed += 1
            if progress_callback:
                progress_callback(index, total)
            continue
        try:
            with transaction.atomic():
                if _find_duplicate(
                    parsed.get("isbn_13"),
                    parsed.get("isbn_10"),
                    parsed["title"],
                    parsed.get("author"),
                ):
                    result.skipped += 1
                    continue

                meta = {}
                if _should_enrich_goodreads_row(parsed):
                    meta = _lookup_metadata_for_import(service, parsed)

                book = _create_book_from_data(parsed, meta)

                if parsed.get("review_text") or parsed.get("rating"):
                    Review.objects.update_or_create(
                        book=book,
                        defaults={
                            "rating": parsed.get("rating"),
                            "review_text": parsed.get("review_text"),
                        },
                    )

                if parsed.get("status"):
                    update_reading_log(book.reading_log, {"status": parsed["status"]})
                    _apply_goodreads_import_dates(book, parsed)

                for shelf_name in parsed.get("shelf_names", []):
                    shelf, _ = Shelf.objects.get_or_create(name=shelf_name)
                    BookshelfItem.objects.get_or_create(book=book, shelf=shelf)

                result.added += 1
        except ValueError as exc:
            if str(exc).startswith("duplicate:"):
                result.skipped += 1
            else:
                result.failed += 1
                result.errors.append(str(exc))
        except Exception as exc:
            result.failed += 1
            result.errors.append(str(exc))
        finally:
            if progress_callback:
                progress_callback(index, total)
            if should_stop and should_stop():
                break

    return result


STORYGRAPH_STATUS_MAP = {
    "read": ReadingStatus.FINISHED,
    "currently reading": ReadingStatus.READING,
    "to-read": ReadingStatus.NOT_STARTED,
    "did-not-finish": ReadingStatus.ABANDONED,
}


def _parse_storygraph_isbn(value: str) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    cleaned = re.sub(r"[^0-9Xx]", "", value.strip())
    if len(cleaned) == 13 and cleaned.isdigit():
        return cleaned, None
    if len(cleaned) == 10:
        return None, cleaned.upper()
    return None, None


def _parse_storygraph_rating(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        rating = float(value)
    except ValueError:
        return None
    if rating <= 0:
        return None
    return max(1, min(5, int(rating + 0.5)))


def _parse_storygraph_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_storygraph_dates_read(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    if "-" in value:
        end_part = value.split("-")[-1].strip()
        if end_part:
            parsed = _parse_storygraph_date(end_part)
            if parsed:
                return parsed
        start_part = value.split("-")[0].strip()
        return _parse_storygraph_date(start_part)
    return _parse_storygraph_date(value)


def _parse_storygraph_row(row: dict) -> dict:
    title = row.get("Title", "").strip()
    authors_raw = row.get("Authors", "").strip()
    authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
    author = authors[0] if authors else ""

    isbn_13, isbn_10 = _parse_storygraph_isbn(row.get("ISBN/UID", ""))

    status_raw = row.get("Read Status", "").strip().lower()
    status = STORYGRAPH_STATUS_MAP.get(status_raw)

    rating = _parse_storygraph_rating(row.get("Star Rating", ""))

    tags_raw = row.get("Tags", "").strip()
    shelf_names = [t.strip().replace("-", " ") for t in tags_raw.split(",") if t.strip()]

    date_read = _parse_storygraph_dates_read(row.get("Dates Read", ""))
    if not date_read:
        date_read = _parse_storygraph_date(row.get("Last Date Read", ""))

    return {
        "title": title,
        "author": author,
        "authors": authors,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "rating": rating,
        "status": status,
        "review_text": row.get("Review", "").strip() or None,
        "shelf_names": shelf_names,
        "date_read": date_read,
        "date_added": _parse_storygraph_date(row.get("Date Added", "")),
    }


def detect_csv_import_kind(file) -> str:
    from books.models import ImportJobKind

    rows = _read_csv_rows(file)
    if not rows:
        return ImportJobKind.GOODREADS_CSV
    headers = set(rows[0].keys())
    if "Read Status" in headers or ("Authors" in headers and "Author" not in headers):
        return ImportJobKind.STORYGRAPH_CSV
    return ImportJobKind.GOODREADS_CSV


def preview_storygraph_csv(file) -> list[dict]:
    preview = []
    for row in _read_csv_rows(file):
        parsed = _parse_storygraph_row(row)
        if not parsed["title"]:
            continue
        dup = _find_duplicate(
            parsed.get("isbn_13"),
            parsed.get("isbn_10"),
            parsed["title"],
            parsed.get("author"),
        )
        parsed["is_duplicate"] = dup is not None
        parsed["duplicate_id"] = str(dup.id) if dup else None
        preview.append(_serialize_preview_row(parsed))
    return preview


def import_storygraph_csv(
    file,
    progress_callback: ProgressCallback | None = None,
    should_stop: ShouldStop = None,
) -> ImportResult:
    result = ImportResult()
    service = MetadataService()
    all_rows = _read_csv_rows(file)
    total = len(all_rows)

    for index, row in enumerate(all_rows, start=1):
        parsed = _parse_storygraph_row(row)
        if not parsed["title"]:
            result.failed += 1
            if progress_callback:
                progress_callback(index, total)
            continue
        try:
            with transaction.atomic():
                if _find_duplicate(
                    parsed.get("isbn_13"),
                    parsed.get("isbn_10"),
                    parsed["title"],
                    parsed.get("author"),
                ):
                    result.skipped += 1
                    continue

                meta = {}
                if _should_enrich_goodreads_row(parsed):
                    meta = _lookup_metadata_for_import(service, parsed)

                book = _create_book_from_data(parsed, meta)

                if parsed.get("review_text") or parsed.get("rating"):
                    Review.objects.update_or_create(
                        book=book,
                        defaults={
                            "rating": parsed.get("rating"),
                            "review_text": parsed.get("review_text"),
                        },
                    )

                if parsed.get("status"):
                    update_reading_log(book.reading_log, {"status": parsed["status"]})
                    _apply_goodreads_import_dates(book, parsed)

                for shelf_name in parsed.get("shelf_names", []):
                    shelf, _ = Shelf.objects.get_or_create(name=shelf_name)
                    BookshelfItem.objects.get_or_create(book=book, shelf=shelf)

                result.added += 1
        except ValueError as exc:
            if str(exc).startswith("duplicate:"):
                result.skipped += 1
            else:
                result.failed += 1
                result.errors.append(str(exc))
        except Exception as exc:
            result.failed += 1
            result.errors.append(str(exc))
        finally:
            if progress_callback:
                progress_callback(index, total)
            if should_stop and should_stop():
                break

    return result


def export_json() -> dict:
    books = Book.objects.prefetch_related("authors", "genres").select_related("reading_log", "review")
    data = []
    for book in books:
        log = getattr(book, "reading_log", None)
        review = getattr(book, "review", None)
        data.append({
            "id": str(book.id),
            "title": book.title,
            "subtitle": book.subtitle,
            "isbn_13": book.isbn_13,
            "isbn_10": book.isbn_10,
            "pages": book.pages,
            "published_year": book.published_year,
            "publisher": book.publisher,
            "description": book.description,
            "cover_url": book.cover_url,
            "language": book.language,
            "authors": [a.name for a in book.authors.all()],
            "genres": [g.name for g in book.genres.all()],
            "status": log.status if log else ReadingStatus.NOT_STARTED,
            "rating": review.rating if review else None,
            "review_text": review.review_text if review else None,
            "shelves": list(
                Shelf.objects.filter(bookshelf_items__book=book).values_list("name", flat=True)
            ),
            "created_at": book.created_at.isoformat(),
        })
    return {"books": data, "version": "0.1.0"}


def export_csv() -> str:
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "Additional Authors", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
        "Date Read", "Date Added",
    ])

    books = Book.objects.prefetch_related("authors", "genres").select_related("reading_log", "review")
    status_to_shelf = {
        ReadingStatus.FINISHED: "read",
        ReadingStatus.READING: "currently-reading",
        ReadingStatus.NOT_STARTED: "to-read",
    }

    for book in books:
        ordered_authors = list(book.authors.order_by("book_authors__position"))
        author = ordered_authors[0] if ordered_authors else None
        additional = ", ".join(a.name for a in ordered_authors[1:])
        log = getattr(book, "reading_log", None)
        review = getattr(book, "review", None)
        exclusive = status_to_shelf.get(log.status if log else ReadingStatus.NOT_STARTED, "to-read")
        shelves = ", ".join(
            Shelf.objects.filter(bookshelf_items__book=book).values_list("name", flat=True)
        )
        date_read = ""
        if log and log.finished_at:
            date_read = log.finished_at.strftime("%Y/%m/%d")
        date_added = book.created_at.strftime("%Y/%m/%d") if book.created_at else ""
        writer.writerow([
            book.title,
            author.name if author else "",
            additional,
            f'="{book.isbn_10}"' if book.isbn_10 else "",
            f'="{book.isbn_13}"' if book.isbn_13 else "",
            review.rating if review and review.rating else "0",
            review.review_text if review and review.review_text else "",
            book.pages or "",
            book.published_year or "",
            book.publisher or "",
            exclusive,
            shelves,
            date_read,
            date_added,
        ])

    return output.getvalue()
