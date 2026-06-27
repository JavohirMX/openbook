"""Hardcover.app GraphQL metadata provider (optional API token)."""

from __future__ import annotations

import logging
import re
from typing import Callable

import requests
from django.conf import settings

from books.genre_normalize import normalize_metadata_genres
from books.isbn import normalize_isbn

logger = logging.getLogger(__name__)

_ISBN_LOOKUP_QUERY = """
query LookupEditionByISBN($isbn: String!) {
  editions(where: {isbn_13: {_eq: $isbn}}, limit: 1) {
    id
    title
    subtitle
    isbn_13
    isbn_10
    pages
    release_date
    publisher { name }
    book {
      title
      subtitle
      description
      contributions { author { name } }
      featured_series { series { name } position }
      cached_tags
    }
    cached_image
  }
}
"""

_SEARCH_QUERY = """
query SearchBooks($query: String!) {
  search(query: $query, query_type: "Book", per_page: 8) {
    results
  }
}
"""


def hardcover_enabled() -> bool:
    return bool(
        getattr(settings, "METADATA_HARDCOVER_ENABLED", True)
        and getattr(settings, "HARDCOVER_API_TOKEN", "").strip()
    )


def _api_url() -> str:
    return getattr(settings, "HARDCOVER_API_URL", "https://api.hardcover.app/v1/graphql").strip()


def _headers() -> dict[str, str]:
    token = getattr(settings, "HARDCOVER_API_TOKEN", "").strip()
    return {
        "Content-Type": "application/json",
        "Authorization": token,
    }


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{4}", str(value))
    if match:
        year = int(match.group())
        return year if 1000 <= year <= 2100 else None
    return None


def _cover_from_cached_image(cached_image) -> str | None:
    if not cached_image:
        return None
    if isinstance(cached_image, str):
        return cached_image if cached_image.startswith("http") else None
    if isinstance(cached_image, dict):
        for key in ("url", "large", "medium", "small"):
            url = cached_image.get(key)
            if url and str(url).startswith("http"):
                return str(url)
    return None


def _edition_to_metadata(edition: dict) -> dict:
    book = edition.get("book") or {}
    contributions = book.get("contributions") or []
    authors = [
        c.get("author", {}).get("name")
        for c in contributions
        if c.get("author", {}).get("name")
    ]

    publisher_name = (edition.get("publisher") or {}).get("name")
    featured = book.get("featured_series") or {}
    series_info = featured.get("series") or {}
    series_name = series_info.get("name")
    series_position = featured.get("position")

    tags = book.get("cached_tags") or []
    genre_names = []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str):
                genre_names.append(tag)
            elif isinstance(tag, dict) and tag.get("name"):
                genre_names.append(str(tag["name"]))

    isbn_13 = edition.get("isbn_13")
    isbn_10 = edition.get("isbn_10")
    if isbn_13:
        norm = normalize_isbn(str(isbn_13))
        if norm:
            isbn_13 = norm.isbn_13
            isbn_10 = isbn_10 or norm.isbn_10

    result = {
        "title": edition.get("title") or book.get("title"),
        "subtitle": edition.get("subtitle") or book.get("subtitle"),
        "authors": authors,
        "pages": edition.get("pages"),
        "publisher": publisher_name,
        "published_year": _parse_year(edition.get("release_date")),
        "description": book.get("description"),
        "cover_url": _cover_from_cached_image(edition.get("cached_image")),
        "genres": normalize_metadata_genres(genre_names),
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "series_name": series_name,
        "series_position": series_position,
        "hardcover_edition_id": str(edition["id"]) if edition.get("id") else None,
        "source": "hardcover",
    }
    return {k: v for k, v in result.items() if v is not None and v != "" and v != []}


def _graphql(
    session: requests.Session,
    query: str,
    variables: dict,
    *,
    post_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict | None:
    payload = {"query": query, "variables": variables}
    if post_fn:
        response = post_fn(_api_url(), json=payload, import_context=import_context)
    else:
        try:
            response = session.post(
                _api_url(),
                json=payload,
                headers=_headers(),
                timeout=(5, 15),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            log = logger.info if import_context else logger.warning
            log("Hardcover request failed: %s", exc)
            return None
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    if body.get("errors"):
        log = logger.info if import_context else logger.warning
        log("Hardcover GraphQL errors: %s", body["errors"])
        return None
    return body.get("data")


def lookup_isbn_hardcover(
    isbn_13: str,
    session: requests.Session,
    *,
    post_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict | None:
    if not hardcover_enabled():
        return {}

    data = _graphql(
        session,
        _ISBN_LOOKUP_QUERY,
        {"isbn": isbn_13},
        post_fn=post_fn,
        import_context=import_context,
    )
    if not data:
        return None

    editions = data.get("editions") or []
    if not editions:
        return {}

    return _edition_to_metadata(editions[0])


def search_hardcover(
    query: str,
    session: requests.Session,
    *,
    limit: int = 8,
    post_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> list[dict]:
    if not hardcover_enabled() or not query.strip():
        return []

    data = _graphql(
        session,
        _SEARCH_QUERY,
        {"query": query},
        post_fn=post_fn,
        import_context=import_context,
    )
    if not data:
        return []

    hits = data.get("search", {}).get("results") or []
    results: list[dict] = []
    for hit in hits[:limit]:
        if not isinstance(hit, dict):
            continue
        meta = {
            "title": hit.get("title"),
            "subtitle": hit.get("subtitle"),
            "authors": hit.get("author_names") or [],
            "isbn_13": (hit.get("isbns") or [None])[0] if hit.get("isbns") else None,
            "pages": hit.get("pages"),
            "published_year": hit.get("release_year"),
            "description": hit.get("description"),
            "cover_url": hit.get("image"),
            "genres": normalize_metadata_genres(hit.get("genres") or []),
            "series_name": (hit.get("series_names") or [None])[0] if hit.get("series_names") else None,
            "series_position": hit.get("featured_series_position"),
            "source": "hardcover",
        }
        cleaned = {k: v for k, v in meta.items() if v is not None and v != "" and v != []}
        if cleaned.get("title"):
            results.append(cleaned)
    return results
