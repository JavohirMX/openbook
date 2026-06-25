import logging

import requests
from django.conf import settings
from django.core.cache import cache

from books.isbn import normalize_isbn

logger = logging.getLogger(__name__)

USER_AGENT = "openbook/0.1.0 (+https://books.javohirmx.com)"
TIMEOUT = 5
RETRY_COUNT = 1
CACHE_TTL = 60 * 60 * 24 * 30  # 30 days


class MetadataService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def lookup_isbn(self, isbn: str) -> dict:
        normalized = normalize_isbn(isbn)
        if not normalized or not normalized.isbn_13:
            return {}

        cache_key = f"metadata:isbn:{normalized.isbn_13}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        result = self._lookup_open_library(normalized.isbn_13)
        if not result:
            result = self._lookup_google_books(normalized.isbn_13)

        cache.set(cache_key, result, CACHE_TTL)
        return result

    def _get(self, url: str, params: dict | None = None) -> requests.Response | None:
        for attempt in range(RETRY_COUNT + 1):
            try:
                response = self.session.get(url, params=params, timeout=TIMEOUT)
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                logger.warning("Metadata request failed (attempt %s): %s", attempt + 1, exc)
        return None

    def _lookup_open_library(self, isbn_13: str) -> dict:
        url = f"{settings.OPENLIBRARY_BASE_URL.rstrip('/')}/api/books"
        response = self._get(
            url,
            params={
                "bibkeys": f"ISBN:{isbn_13}",
                "format": "json",
                "jscmd": "data",
            },
        )
        if response is None:
            return {}

        data = response.json()
        book_data = data.get(f"ISBN:{isbn_13}")
        if not book_data:
            return {}

        authors = [a.get("name", "") for a in book_data.get("authors", []) if a.get("name")]
        publishers = book_data.get("publishers", [])
        publisher = publishers[0].get("name") if publishers else None

        subjects = book_data.get("subjects", [])
        genres = [s.get("name", "") for s in subjects if s.get("name")]

        cover_url = self._open_library_cover(isbn_13, book_data.get("cover"))

        return {
            "title": book_data.get("title"),
            "authors": authors,
            "pages": book_data.get("number_of_pages"),
            "publisher": publisher,
            "cover_url": cover_url,
            "genres": genres,
            "subjects": genres,
        }

    def _open_library_cover(self, isbn_13: str, cover: dict | None) -> str | None:
        if cover:
            if cover.get("large"):
                return cover["large"]
            if cover.get("medium"):
                return cover["medium"]
        return f"https://covers.openlibrary.org/b/isbn/{isbn_13}-L.jpg"

    def _lookup_google_books(self, isbn_13: str) -> dict:
        url = f"{settings.GOOGLE_BOOKS_BASE_URL.rstrip('/')}/volumes"
        response = self._get(url, params={"q": f"isbn:{isbn_13}"})
        if response is None:
            return {}

        data = response.json()
        items = data.get("items", [])
        if not items:
            return {}

        volume_info = items[0].get("volumeInfo", {})
        image_links = volume_info.get("imageLinks", {})

        return {
            "title": volume_info.get("title"),
            "authors": volume_info.get("authors", []),
            "pages": volume_info.get("pageCount"),
            "publisher": volume_info.get("publisher"),
            "cover_url": image_links.get("thumbnail"),
            "genres": volume_info.get("categories", []),
            "subjects": volume_info.get("categories", []),
        }
