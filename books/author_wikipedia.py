"""Fetch author biography and links from Wikipedia."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "openbook/0.1.0 (self-hosted book tracker)"


def fetch_author_wikipedia(name: str) -> dict | None:
    if not name.strip():
        return None
    try:
        search = requests.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": name,
                "format": "json",
                "srlimit": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        search.raise_for_status()
        hits = search.json().get("query", {}).get("search", [])
        if not hits:
            return None
        page_title = hits[0]["title"]

        summary = requests.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "prop": "extracts|pageimages",
                "exintro": 1,
                "explaintext": 1,
                "pithumbsize": 300,
                "titles": page_title,
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        summary.raise_for_status()
        pages = summary.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        if page.get("missing"):
            return None

        bio = (page.get("extract") or "").strip()
        thumb = page.get("thumbnail", {}).get("source")
        slug = page_title.replace(" ", "_")
        return {
            "bio": bio[:4000] if bio else None,
            "wikipedia_url": f"https://en.wikipedia.org/wiki/{slug}",
            "photo_url": thumb,
        }
    except requests.RequestException:
        logger.exception("Wikipedia lookup failed for %s", name)
        return None
