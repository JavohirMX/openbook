import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError

from books.genre_normalize import normalize_metadata_genres
from books.isbn import normalize_isbn

logger = logging.getLogger(__name__)

_cache_unavailable_logged = False


def _cache_get(key: str, default=None):
    global _cache_unavailable_logged
    try:
        return cache.get(key, default)
    except DatabaseError as exc:
        if not _cache_unavailable_logged:
            logger.warning(
                "Metadata cache unavailable (%s); run createcachetable. Lookups will continue without cache.",
                exc,
            )
            _cache_unavailable_logged = True
        return default


def _cache_set(key: str, value, timeout: int) -> None:
    global _cache_unavailable_logged
    try:
        cache.set(key, value, timeout)
    except DatabaseError as exc:
        if not _cache_unavailable_logged:
            logger.warning(
                "Metadata cache unavailable (%s); run createcachetable. Lookups will continue without cache.",
                exc,
            )
            _cache_unavailable_logged = True

CACHE_TTL = 60 * 60 * 24 * 30  # 30 days
NEGATIVE_CACHE_TTL = 60 * 60  # 1 hour
MAX_RETRY_AFTER_SECONDS = 60
# Open Library: 3 req/s with identified User-Agent (email), 1 req/s without
OPENLIBRARY_IDENTIFIED_DELAY_SECONDS = 0.35
OPENLIBRARY_DEFAULT_DELAY_SECONDS = 1.0


def metadata_user_agent() -> str:
    """Build User-Agent per Open Library rate-limit policy (app name + contact)."""
    app_name = getattr(settings, "METADATA_APP_NAME", "openbook")
    version = getattr(settings, "APP_VERSION", "0.1.0")
    contact = getattr(settings, "OPENLIBRARY_CONTACT_EMAIL", "").strip()
    if contact:
        return f"{app_name}/{version} ({contact})"
    site = "https://books.javohirmx.com"
    if settings.ALLOWED_HOSTS:
        host = next((h for h in settings.ALLOWED_HOSTS if "." in h), None)
        if host:
            site = f"https://{host}"
    return f"{app_name}/{version} (+{site})"


def openlibrary_import_delay_seconds() -> float:
    """Pacing delay that respects Open Library request limits."""
    configured = float(getattr(settings, "METADATA_IMPORT_DELAY_SECONDS", 0) or 0)
    if configured > 0:
        return configured
    if getattr(settings, "OPENLIBRARY_CONTACT_EMAIL", "").strip():
        return OPENLIBRARY_IDENTIFIED_DELAY_SECONDS
    return OPENLIBRARY_DEFAULT_DELAY_SECONDS


def _metadata_timeout() -> tuple[float, float]:
    connect = float(getattr(settings, "METADATA_CONNECT_TIMEOUT", 5))
    read = float(getattr(settings, "METADATA_READ_TIMEOUT", 10))
    return (connect, read)


def _retry_count() -> int:
    return int(getattr(settings, "METADATA_RETRY_COUNT", 1))


def _retry_backoff() -> float:
    return float(getattr(settings, "METADATA_RETRY_BACKOFF", 1))


class MetadataService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": metadata_user_agent()})

    def lookup_isbn(self, isbn: str, *, import_context: bool = False) -> dict:
        normalized = normalize_isbn(isbn)
        if not normalized or not normalized.isbn_13:
            return {}

        cache_key = f"metadata:isbn:{normalized.isbn_13}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        isbn_13 = normalized.isbn_13
        ol_result = self._lookup_open_library(isbn_13, import_context=import_context)
        if ol_result and ol_result.get("title"):
            _cache_set(cache_key, ol_result, CACHE_TTL)
            return ol_result

        gb_result = self._lookup_google_books(isbn_13, import_context=import_context)
        if gb_result and gb_result.get("title"):
            _cache_set(cache_key, gb_result, CACHE_TTL)
            return gb_result

        if ol_result is None and gb_result is None:
            return {}

        _cache_set(cache_key, {}, NEGATIVE_CACHE_TTL)
        return {}

    def _get(
        self,
        url: str,
        params: dict | None = None,
        *,
        import_context: bool = False,
    ) -> requests.Response | None:
        log = logger.info if import_context else logger.warning
        retries = _retry_count()

        for attempt in range(retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=_metadata_timeout(),
                )
                if response.status_code == 429:
                    retry_after = self._retry_after_seconds(response)
                    log(
                        "Metadata rate limited (attempt %s), retrying in %ss: %s",
                        attempt + 1,
                        retry_after,
                        url,
                    )
                    if attempt < retries:
                        time.sleep(retry_after)
                        continue
                    return None
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                log("Metadata request failed (attempt %s): %s", attempt + 1, exc)
                if attempt < retries:
                    time.sleep(_retry_backoff() * (2**attempt))
        return None

    def _retry_after_seconds(self, response: requests.Response) -> float:
        raw = response.headers.get("Retry-After", "")
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            seconds = _retry_backoff()
        return min(max(seconds, 0), MAX_RETRY_AFTER_SECONDS)

    def _lookup_open_library(
        self,
        isbn_13: str,
        *,
        import_context: bool = False,
    ) -> dict | None:
        url = f"{settings.OPENLIBRARY_BASE_URL.rstrip('/')}/api/books"
        response = self._get(
            url,
            params={
                "bibkeys": f"ISBN:{isbn_13}",
                "format": "json",
                "jscmd": "data",
            },
            import_context=import_context,
        )
        if response is None:
            return None

        data = response.json()
        book_data = data.get(f"ISBN:{isbn_13}")
        if not book_data:
            return {}

        authors = [a.get("name", "") for a in book_data.get("authors", []) if a.get("name")]
        publishers = book_data.get("publishers", [])
        publisher = publishers[0].get("name") if publishers else None

        subjects = book_data.get("subjects", [])
        raw_genres = [s.get("name", "") for s in subjects if s.get("name")]
        genres = normalize_metadata_genres(raw_genres)

        cover_url = self._open_library_cover(isbn_13, book_data.get("cover"))

        return {
            "title": book_data.get("title"),
            "authors": authors,
            "pages": book_data.get("number_of_pages"),
            "publisher": publisher,
            "cover_url": cover_url,
            "genres": genres,
            "subjects": raw_genres,
            "openlibrary_edition_key": book_data.get("key"),
            "openlibrary_work_id": self._open_library_work_id(book_data),
        }

    def _open_library_work_id(self, book_data: dict) -> str | None:
        works = book_data.get("works") or []
        if works:
            work = works[0]
            if isinstance(work, dict):
                return work.get("key")
            return str(work)
        return None

    def _open_library_cover(self, isbn_13: str, cover: dict | None) -> str | None:
        if cover:
            if cover.get("large"):
                return cover["large"]
            if cover.get("medium"):
                return cover["medium"]
        return f"https://covers.openlibrary.org/b/isbn/{isbn_13}-L.jpg"

    def _lookup_google_books(
        self,
        isbn_13: str,
        *,
        import_context: bool = False,
    ) -> dict | None:
        url = f"{settings.GOOGLE_BOOKS_BASE_URL.rstrip('/')}/volumes"
        response = self._get(
            url,
            params={"q": f"isbn:{isbn_13}"},
            import_context=import_context,
        )
        if response is None:
            return None

        data = response.json()
        items = data.get("items", [])
        if not items:
            return {}

        volume_info = items[0].get("volumeInfo", {})
        image_links = volume_info.get("imageLinks", {})
        raw_categories = volume_info.get("categories", [])
        genres = normalize_metadata_genres(raw_categories)

        return {
            "title": volume_info.get("title"),
            "authors": volume_info.get("authors", []),
            "pages": volume_info.get("pageCount"),
            "publisher": volume_info.get("publisher"),
            "cover_url": image_links.get("thumbnail"),
            "genres": genres,
            "subjects": raw_categories,
            "google_books_id": items[0].get("id"),
        }

    def search_books(self, query: str, *, limit: int = 10, import_context: bool = False) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []

        cache_key = f"metadata:search:{query.lower()[:200]}:{limit}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        results = self._search_open_library(query, limit=limit, import_context=import_context)
        if not results:
            results = self._search_google_books(query, limit=limit, import_context=import_context)

        _cache_set(cache_key, results, CACHE_TTL if results else NEGATIVE_CACHE_TTL)
        return results

    def _search_open_library(
        self,
        query: str,
        *,
        limit: int,
        import_context: bool = False,
    ) -> list[dict]:
        url = f"{settings.OPENLIBRARY_BASE_URL.rstrip('/')}/search.json"
        response = self._get(
            url,
            params={"q": query, "limit": limit, "fields": "key,title,author_name,isbn,cover_i,number_of_pages,publisher,first_publish_year"},
            import_context=import_context,
        )
        if response is None:
            return []

        docs = response.json().get("docs", [])
        results = []
        for doc in docs:
            isbns = doc.get("isbn") or []
            isbn_13 = next((i for i in isbns if len(str(i)) == 13), None)
            isbn_10 = next((i for i in isbns if len(str(i)) == 10), None)
            cover_id = doc.get("cover_i")
            cover_url = f"https://covers.openlibrary.org/b/id/{cover_id}-M.jpg" if cover_id else None
            if not cover_url and isbn_13:
                cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn_13}-M.jpg"
            results.append(
                {
                    "title": doc.get("title"),
                    "authors": doc.get("author_name", []),
                    "isbn_13": isbn_13,
                    "isbn_10": isbn_10,
                    "pages": doc.get("number_of_pages"),
                    "publisher": (doc.get("publisher") or [None])[0],
                    "published_year": doc.get("first_publish_year"),
                    "cover_url": cover_url,
                    "openlibrary_edition_key": doc.get("key"),
                    "source": "open_library",
                }
            )
        return results

    def _search_google_books(
        self,
        query: str,
        *,
        limit: int,
        import_context: bool = False,
    ) -> list[dict]:
        url = f"{settings.GOOGLE_BOOKS_BASE_URL.rstrip('/')}/volumes"
        response = self._get(
            url,
            params={"q": query, "maxResults": limit},
            import_context=import_context,
        )
        if response is None:
            return []

        items = response.json().get("items", [])
        results = []
        for item in items:
            volume_info = item.get("volumeInfo", {})
            identifiers = volume_info.get("industryIdentifiers", [])
            isbn_13 = next((i["identifier"] for i in identifiers if i.get("type") == "ISBN_13"), None)
            isbn_10 = next((i["identifier"] for i in identifiers if i.get("type") == "ISBN_10"), None)
            image_links = volume_info.get("imageLinks", {})
            results.append(
                {
                    "title": volume_info.get("title"),
                    "authors": volume_info.get("authors", []),
                    "isbn_13": isbn_13,
                    "isbn_10": isbn_10,
                    "pages": volume_info.get("pageCount"),
                    "publisher": volume_info.get("publisher"),
                    "published_year": (volume_info.get("publishedDate") or "")[:4] or None,
                    "cover_url": image_links.get("thumbnail"),
                    "google_books_id": item.get("id"),
                    "source": "google_books",
                }
            )
        return results
