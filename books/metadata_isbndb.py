"""ISBNdb API v2 metadata provider (optional paid API key)."""

from __future__ import annotations

import logging
import re
from typing import Callable

import requests
from django.conf import settings

from books.genre_normalize import normalize_metadata_genres

logger = logging.getLogger(__name__)

_BATCH_MAX = 100


def isbndb_enabled() -> bool:
    return bool(getattr(settings, "ISBNDB_API_KEY", "").strip())


def _api_base() -> str:
    return getattr(settings, "ISBNDB_API_URL", "https://api2.isbndb.com").rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": getattr(settings, "ISBNDB_API_KEY", "").strip(),
    }


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", str(value))
    if match:
        year = int(match.group())
        return year if 1000 <= year <= 2100 else None
    return None


def _book_payload_to_metadata(book: dict) -> dict:
    authors = book.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(",") if a.strip()]

    subjects = book.get("subjects") or book.get("subject") or []
    if isinstance(subjects, str):
        subjects = [s.strip() for s in subjects.split(",") if s.strip()]

    result = {
        "title": book.get("title") or book.get("title_long"),
        "subtitle": book.get("edition"),
        "authors": authors,
        "pages": book.get("pages"),
        "publisher": book.get("publisher"),
        "published_year": _parse_year(book.get("date_published") or book.get("publish_date")),
        "description": book.get("synopsis") or book.get("overview"),
        "cover_url": book.get("image"),
        "genres": normalize_metadata_genres(subjects),
        "isbn_13": book.get("isbn13"),
        "isbn_10": book.get("isbn10") or book.get("isbn"),
        "language": book.get("language"),
        "source": "isbndb",
    }
    return {k: v for k, v in result.items() if v is not None and v != "" and v != []}


def lookup_isbn_isbndb(
    isbn_13: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict | None:
    if not isbndb_enabled():
        return {}

    url = f"{_api_base()}/book/{isbn_13}"
    if get_fn:
        response = get_fn(url, headers=_headers(), import_context=import_context)
    else:
        try:
            response = session.get(url, headers=_headers(), timeout=(5, 15))
            response.raise_for_status()
        except requests.RequestException as exc:
            log = logger.info if import_context else logger.warning
            log("ISBNdb request failed: %s", exc)
            return None

    if response is None:
        return None

    book = response.json().get("book")
    if not book:
        return {}
    return _book_payload_to_metadata(book)


def lookup_isbns_batch(
    isbns: list[str],
    session: requests.Session,
    *,
    post_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict[str, dict]:
    """Batch ISBN lookup; returns mapping isbn_13 -> metadata dict."""
    if not isbndb_enabled() or not isbns:
        return {}

    unique = list(dict.fromkeys(isbns))[:_BATCH_MAX]
    url = f"{_api_base()}/books"
    payload = {"isbns": unique}

    if post_fn:
        response = post_fn(url, json=payload, headers=_headers(), import_context=import_context)
    else:
        try:
            response = session.post(
                url,
                json=payload,
                headers=_headers(),
                timeout=(5, 30),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log = logger.info if import_context else logger.warning
            log("ISBNdb batch request failed: %s", exc)
            return {}

    if response is None:
        return {}

    books = response.json().get("books") or response.json().get("data") or []
    result: dict[str, dict] = {}
    for book in books:
        meta = _book_payload_to_metadata(book)
        isbn = meta.get("isbn_13") or book.get("isbn13")
        if isbn and meta:
            result[str(isbn)] = meta
    return result


def parse_ratelimit_remaining(response: requests.Response) -> dict[str, int | None]:
    """Parse ISBNdb ratelimit headers for health stats."""
    remaining: dict[str, int | None] = {"daily": None, "per_minute": None}
    header = response.headers.get("ratelimit", "")
    for part in header.split(","):
        part = part.strip().strip('"')
        if "daily" in part and "r=" in part:
            try:
                remaining["daily"] = int(part.split("r=")[1].split(";")[0])
            except (IndexError, ValueError):
                pass
        if "rate" in part and "r=" in part:
            try:
                remaining["per_minute"] = int(part.split("r=")[1].split(";")[0])
            except (IndexError, ValueError):
                pass
    return remaining
