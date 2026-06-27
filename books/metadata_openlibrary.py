"""Open Library work/edition deep fetch for hydrating sparse metadata."""

from __future__ import annotations

import logging
from typing import Callable

import requests
from django.conf import settings

from books.genre_normalize import normalize_metadata_genres
from books.covers import resolve_openlibrary_cover_url

logger = logging.getLogger(__name__)


def _normalize_key(key: str | None, prefix: str) -> str | None:
    if not key:
        return None
    key = str(key).strip()
    if key.startswith(prefix):
        return key
    if key.startswith("/"):
        return key
    return f"{prefix}{key}"


def fetch_work(
    work_key: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict:
    """Fetch Open Library work JSON and return a metadata dict fragment."""
    key = _normalize_key(work_key, "/works/")
    if not key:
        return {}

    base = settings.OPENLIBRARY_BASE_URL.rstrip("/")
    ol_key = key.lstrip("/")
    url = f"{base}/{ol_key}.json"
    data = _fetch_json(url, session, get_fn=get_fn, import_context=import_context)
    if not data:
        return {}

    subjects = data.get("subjects", []) or []
    if subjects and isinstance(subjects[0], dict):
        raw_genres = [s.get("name", "") for s in subjects if isinstance(s, dict)]
    else:
        raw_genres = [str(s) for s in subjects if s]

    genres = normalize_metadata_genres(raw_genres)
    description = data.get("description")
    if isinstance(description, dict):
        description = description.get("value")

    covers = data.get("covers") or []
    cover_id = covers[0] if covers and covers[0] > 0 else None
    cover_url = resolve_openlibrary_cover_url(cover_id=cover_id) if cover_id else None

    return {
        "title": data.get("title"),
        "description": description if isinstance(description, str) else None,
        "genres": genres,
        "subjects": raw_genres,
        "cover_url": cover_url,
        "openlibrary_work_id": key if key.startswith("/") else f"/works/{key}",
        "published_year": data.get("first_publish_date", "")[:4] or None
        if isinstance(data.get("first_publish_date"), str)
        else None,
        "source": "open_library",
    }


def fetch_edition(
    edition_key: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict:
    """Fetch Open Library edition JSON and return a metadata dict fragment."""
    key = _normalize_key(edition_key, "/books/")
    if not key:
        return {}

    base = settings.OPENLIBRARY_BASE_URL.rstrip("/")
    ol_key = key.lstrip("/")
    url = f"{base}/{ol_key}.json"
    data = _fetch_json(url, session, get_fn=get_fn, import_context=import_context)
    if not data:
        return {}

    publishers = data.get("publishers") or []
    publisher = publishers[0] if publishers else None

    isbn_13 = None
    isbn_10 = None
    for isbn in data.get("isbn_13") or []:
        if len(str(isbn)) == 13:
            isbn_13 = str(isbn)
            break
    for isbn in data.get("isbn_10") or []:
        if len(str(isbn)) == 10:
            isbn_10 = str(isbn)
            break

    covers = data.get("covers") or []
    cover_id = covers[0] if covers and covers[0] > 0 else None
    edition_olid = key if key.startswith("/") else f"/books/{key}"
    cover_url = resolve_openlibrary_cover_url(
        cover_id=cover_id,
        edition_olid=edition_olid,
        isbn_13=isbn_13,
        isbn_10=isbn_10,
    )
    work_key = None
    works = data.get("works") or []
    if works:
        w = works[0]
        work_key = w.get("key") if isinstance(w, dict) else str(w)

    return {
        "title": data.get("title"),
        "pages": data.get("number_of_pages"),
        "publisher": publisher,
        "cover_url": cover_url,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "openlibrary_edition_key": key if key.startswith("/") else f"/books/{key}",
        "openlibrary_work_id": work_key,
        "published_year": data.get("publish_date", "")[:4] or None
        if isinstance(data.get("publish_date"), str)
        else None,
        "source": "open_library",
    }


def hydrate_candidate(
    candidate: dict,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict:
    """Enrich a sparse search/lookup candidate with work/edition API data."""
    from books.metadata_merge import merge_metadata_best_per_field

    parts = [candidate]
    work_id = candidate.get("openlibrary_work_id")
    edition_key = candidate.get("openlibrary_edition_key")

    if edition_key:
        edition_data = fetch_edition(
            edition_key, session, get_fn=get_fn, import_context=import_context
        )
        if edition_data:
            parts.append(edition_data)
            if not work_id:
                work_id = edition_data.get("openlibrary_work_id")

    if work_id:
        work_data = fetch_work(work_id, session, get_fn=get_fn, import_context=import_context)
        if work_data:
            parts.append(work_data)

    if len(parts) == 1:
        return candidate
    return merge_metadata_best_per_field(*parts, book_context=candidate)


def _fetch_json(
    url: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict | None:
    if get_fn:
        response = get_fn(url, import_context=import_context)
    else:
        try:
            response = session.get(url, timeout=(5, 10))
            response.raise_for_status()
        except requests.RequestException as exc:
            log = logger.info if import_context else logger.warning
            log("Open Library fetch failed: %s", exc)
            return None

    if response is None:
        return None
    try:
        return response.json()
    except ValueError:
        return None
