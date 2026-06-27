"""Internet Archive cover fallback for ISBN lookups."""

from __future__ import annotations

import logging
import time
from typing import Callable

import requests

logger = logging.getLogger(__name__)

ARCHIVE_SEARCH_URL = "https://archive.org/advancedsearch.php"
ARCHIVE_COVER_BASE = "https://archive.org/services/img"
_ARCHIVE_DELAY_SECONDS = 1.0


def lookup_archive_cover(
    isbn_13: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict | None:
    """Return metadata dict with cover_url only when Archive.org has a match."""
    query = f"isbn:{isbn_13} AND mediatype:texts"
    params = {
        "q": query,
        "fl[]": ["identifier", "title"],
        "rows": 1,
        "page": 1,
        "output": "json",
    }

    if get_fn:
        response = get_fn(ARCHIVE_SEARCH_URL, params=params, import_context=import_context)
    else:
        try:
            response = session.get(ARCHIVE_SEARCH_URL, params=params, timeout=(5, 15))
            response.raise_for_status()
        except requests.RequestException as exc:
            log = logger.info if import_context else logger.warning
            log("Archive.org request failed: %s", exc)
            return {}

    if response is None:
        return None

    docs = response.json().get("response", {}).get("docs", [])
    if not docs:
        return {}

    identifier = docs[0].get("identifier")
    if not identifier:
        return {}

    time.sleep(_ARCHIVE_DELAY_SECONDS)
    return {
        "cover_url": f"{ARCHIVE_COVER_BASE}/{identifier}",
        "source": "archive_org",
    }
