"""Merge metadata dicts from multiple providers using per-field best-value rules."""

from __future__ import annotations

import re
from typing import Any

from books.genre_normalize import normalize_metadata_genres
from books.isbn import normalize_isbn

_COVER_PRIORITY = (
    ("open_library", 100),
    ("open_library_isbn", 90),
    ("hardcover", 85),
    ("google_books", 70),
    ("wikidata", 60),
    ("archive_org", 55),
    ("isbndb", 50),
)

_SOURCE_RANK = {name: rank for name, rank in _COVER_PRIORITY}


def _normalize_title(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _author_last_name(author: str) -> str:
    parts = (author or "").strip().split()
    return parts[-1].lower() if parts else ""


def _cover_score(candidate: dict) -> int:
    url = candidate.get("cover_url") or ""
    source = candidate.get("source") or ""
    if not url:
        return 0
    score = _SOURCE_RANK.get(source, 50)
    if "covers.openlibrary.org/b/id/" in url:
        score = max(score, 95)
    if "-L.jpg" in url or "large" in url.lower():
        score += 10
    if "thumbnail" in url.lower() or "=zoom" in url:
        score -= 5
    return score


def _parse_year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2100 else None
    match = re.search(r"\d{4}", str(value))
    if match:
        year = int(match.group())
        return year if 1000 <= year <= 2100 else None
    return None


def _best_pages(candidates: list[dict]) -> int | None:
    pages = [c.get("pages") for c in candidates if c.get("pages")]
    if not pages:
        return None
    return max(int(p) for p in pages if isinstance(p, (int, float)) and p > 0)


def _best_publisher(candidates: list[dict]) -> str | None:
    for c in candidates:
        pub = c.get("publisher")
        if pub and str(pub).strip():
            return str(pub).strip()
    return None


def _best_year(candidates: list[dict]) -> int | None:
    for c in candidates:
        year = _parse_year(c.get("published_year"))
        if year:
            return year
    return None


def _best_cover(candidates: list[dict]) -> str | None:
    scored = [(c, _cover_score(c)) for c in candidates]
    scored = [(c, s) for c, s in scored if s > 0]
    if not scored:
        return None
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0].get("cover_url")


def _best_description(candidates: list[dict]) -> str | None:
    texts = [str(c.get("description", "")).strip() for c in candidates]
    texts = [t for t in texts if t]
    return max(texts, key=len) if texts else None


def _best_title(candidates: list[dict]) -> str | None:
    for c in candidates:
        title = c.get("title")
        if title and str(title).strip():
            return str(title).strip()
    return None


def _merge_authors(candidates: list[dict], book_context: dict | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    context_authors = (book_context or {}).get("authors") or []
    context_last = _author_last_name(context_authors[0]) if context_authors else ""

    def add(name: str) -> None:
        key = name.lower().strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(name.strip())

    ranked_candidates = list(candidates)
    if context_last:
        ranked_candidates.sort(
            key=lambda c: (
                0
                if context_last
                and any(_author_last_name(a) == context_last for a in (c.get("authors") or []))
                else 1
            )
        )

    for c in ranked_candidates:
        for author in c.get("authors") or []:
            if author:
                add(str(author))
    return ordered


def _merge_genres(candidates: list[dict]) -> list[str]:
    raw: list[str] = []
    for c in candidates:
        raw.extend(c.get("subjects") or [])
        raw.extend(c.get("genres") or [])
    return normalize_metadata_genres(raw)


def _best_isbns(candidates: list[dict]) -> tuple[str | None, str | None]:
    isbn_13 = None
    isbn_10 = None
    for c in candidates:
        raw_13 = c.get("isbn_13")
        raw_10 = c.get("isbn_10")
        if raw_13 and not isbn_13:
            norm = normalize_isbn(str(raw_13))
            if norm and norm.isbn_13:
                isbn_13 = norm.isbn_13
        if raw_10 and not isbn_10:
            norm = normalize_isbn(str(raw_10))
            if norm and norm.isbn_10:
                isbn_10 = norm.isbn_10
        if isbn_13 and isbn_10:
            break
    if isbn_13 and not isbn_10:
        norm = normalize_isbn(isbn_13)
        if norm and norm.isbn_10:
            isbn_10 = norm.isbn_10
    return isbn_13, isbn_10


def _first_non_empty(candidates: list[dict], key: str) -> Any:
    for c in candidates:
        val = c.get(key)
        if val is not None and val != "":
            return val
    return None


def merge_metadata_best_per_field(
    *candidates: dict,
    book_context: dict | None = None,
) -> dict:
    """Merge provider payloads; later candidates do not override earlier unless better per field."""
    valid = []
    for c in candidates:
        if not c:
            continue
        item = dict(c)
        if item.get("cover_url") and "openlibrary.org" in item["cover_url"] and not item.get("source"):
            item["source"] = "open_library"
        if item.get("cover_url") and "covers.openlibrary.org/b/isbn/" in item.get("cover_url", ""):
            item["source"] = item.get("source") or "open_library_isbn"
        valid.append(item)
    if not valid:
        return {}
    isbn_13, isbn_10 = _best_isbns(valid)
    merged: dict[str, Any] = {
        "title": _best_title(valid),
        "authors": _merge_authors(valid, book_context),
        "pages": _best_pages(valid),
        "publisher": _best_publisher(valid),
        "published_year": _best_year(valid),
        "cover_url": _best_cover(valid),
        "description": _best_description(valid),
        "genres": _merge_genres(valid),
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "openlibrary_work_id": _first_non_empty(valid, "openlibrary_work_id"),
        "openlibrary_edition_key": _first_non_empty(valid, "openlibrary_edition_key"),
        "google_books_id": _first_non_empty(valid, "google_books_id"),
        "wikidata_id": _first_non_empty(valid, "wikidata_id"),
        "hardcover_edition_id": _first_non_empty(valid, "hardcover_edition_id"),
        "series_name": _first_non_empty(valid, "series_name"),
        "series_position": _first_non_empty(valid, "series_position"),
        "narrator": _first_non_empty(valid, "narrator"),
    }
    sources = sorted({c.get("source") for c in valid if c.get("source")})
    if sources:
        merged["source_summary"] = "+".join(sources)
    return {k: v for k, v in merged.items() if v is not None and v != "" and v != []}
