"""Conditional provider chain rules for metadata lookup."""

from __future__ import annotations


def _has_title(meta: dict) -> bool:
    return bool((meta.get("title") or "").strip())


def _is_present(meta: dict, field: str) -> bool:
    value = meta.get(field)
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    return True


def _strict_needs_google_books(merged: dict) -> bool:
    if not _has_title(merged):
        return True
    if not _is_present(merged, "authors"):
        return True
    if not _is_present(merged, "cover_url") and not _is_present(merged, "pages"):
        return True
    return False


def needs_google_books(merged: dict, *, import_context: bool) -> bool:
    if _strict_needs_google_books(merged):
        return True
    if import_context:
        return False
    for field in ("description", "published_year", "publisher"):
        if not _is_present(merged, field):
            return True
    return False


def needs_wikidata(merged: dict, *, import_context: bool) -> bool:
    if not _has_title(merged):
        return True
    if import_context:
        return False
    if (
        not _is_present(merged, "cover_url")
        and not _is_present(merged, "genres")
        and not _is_present(merged, "description")
    ):
        return True
    return False


def needs_hardcover(merged: dict, *, import_context: bool) -> bool:
    if not _has_title(merged):
        return False
    if not _is_present(merged, "cover_url"):
        return True
    if not _is_present(merged, "series_name"):
        return True
    if import_context:
        return False
    if not _is_present(merged, "subtitle"):
        return True
    if not _is_present(merged, "description"):
        return True
    return False


def needs_archive_cover(merged: dict) -> bool:
    return _has_title(merged) and not _is_present(merged, "cover_url")


def needs_isbndb(merged: dict, *, import_context: bool) -> bool:
    del import_context
    if not _has_title(merged):
        return True
    if not _is_present(merged, "cover_url"):
        return True
    if not _is_present(merged, "description"):
        return True
    if not _is_present(merged, "publisher"):
        return True
    return False


def needs_more_search_results(results: list[dict], limit: int) -> bool:
    threshold = min(3, limit)
    titled = [r for r in results if _has_title(r)]
    return len(titled) < threshold
