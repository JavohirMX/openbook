import logging
import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError

from books.covers import resolve_openlibrary_cover_url
from books.genre_normalize import normalize_metadata_genres
from books.isbn import normalize_isbn
from books.metadata_cache_keys import metadata_search_cache_key
from books.metadata_chain import (
    needs_archive_cover,
    needs_google_books,
    needs_hardcover,
    needs_isbndb,
    needs_more_search_results,
    needs_wikidata,
)
from books.metadata_merge import merge_metadata_best_per_field
from books.metadata_openlibrary import hydrate_candidate
from books.metadata_archive import lookup_archive_cover
from books.metadata_hardcover import (
    hardcover_enabled,
    lookup_isbn_hardcover,
    search_hardcover,
)
from books.metadata_isbndb import isbndb_enabled, lookup_isbn_isbndb
from books.metadata_wikidata import lookup_isbn_wikidata, search_wikidata, wikidata_enabled

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


def metadata_lookup_strategy() -> str:
    return getattr(settings, "METADATA_LOOKUP_STRATEGY", "chain").lower()


def _google_books_params(base: dict | None = None) -> dict:
    params = dict(base or {})
    api_key = getattr(settings, "GOOGLE_BOOKS_API_KEY", "").strip()
    if api_key:
        params["key"] = api_key
    return params


def _provider_payload(result: dict | None) -> dict:
    if not result:
        return {}
    return dict(result)


def _merge_provider_result(merged: dict, result: dict | None, *, source: str) -> dict:
    payload = _provider_payload(result)
    if not payload:
        return merged
    payload.setdefault("source", source)
    if merged:
        return merge_metadata_best_per_field(merged, payload)
    return merge_metadata_best_per_field(payload)


class MetadataService:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": metadata_user_agent()})

    def _cache_get_fn(self, key: str, default=None):
        return _cache_get(key, default)

    def _cache_set_fn(self, key: str, value, timeout: int) -> None:
        _cache_set(key, value, timeout)

    def _get_wikidata(self, url, params=None, *, import_context: bool = False):
        return self._get(url, params=params, import_context=import_context)

    def _post_hardcover(self, url, json=None, *, import_context: bool = False):
        headers = {
            "Content-Type": "application/json",
            "Authorization": getattr(settings, "HARDCOVER_API_TOKEN", "").strip(),
        }
        log = logger.info if import_context else logger.warning
        retries = _retry_count()
        for attempt in range(retries + 1):
            try:
                response = self.session.post(
                    url,
                    json=json,
                    headers=headers,
                    timeout=_metadata_timeout(),
                )
                if response.status_code == 429:
                    retry_after = self._retry_after_seconds(response)
                    log(
                        "Hardcover rate limited (attempt %s), retrying in %ss",
                        attempt + 1,
                        retry_after,
                    )
                    if attempt < retries:
                        time.sleep(retry_after)
                        continue
                    return None
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                log("Hardcover request failed (attempt %s): %s", attempt + 1, exc)
                if attempt < retries:
                    time.sleep(_retry_backoff())
                    continue
                return None
        return None

    def _get_isbndb(self, url, headers=None, *, import_context: bool = False):
        log = logger.info if import_context else logger.warning
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=_metadata_timeout(),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            log("ISBNdb request failed: %s", exc)
            return None

    def _post_isbndb(self, url, json=None, headers=None, *, import_context: bool = False):
        log = logger.info if import_context else logger.warning
        try:
            response = self.session.post(
                url,
                json=json,
                headers=headers,
                timeout=_metadata_timeout(),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            log("ISBNdb batch request failed: %s", exc)
            return None

    def _get_openlibrary_json(self, url, params=None, *, import_context: bool = False):
        if params:
            return self._get(url, params=params, import_context=import_context)
        return self._get(url, import_context=import_context)

    def lookup_isbn(self, isbn: str, *, import_context: bool = False) -> dict:
        normalized = normalize_isbn(isbn)
        if not normalized or not normalized.isbn_13:
            return {}

        cache_key = f"metadata:isbn:{normalized.isbn_13}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        isbn_13 = normalized.isbn_13
        merged, ol_result, gb_result, wd_result, gb_attempted, wd_attempted = (
            self._lookup_isbn_parallel(isbn_13, import_context=import_context)
            if metadata_lookup_strategy() == "parallel"
            else self._lookup_isbn_chain(isbn_13, import_context=import_context)
        )

        if merged and (merged.get("openlibrary_work_id") or merged.get("openlibrary_edition_key")):
            merged = hydrate_candidate(
                merged,
                self.session,
                get_fn=self._get_openlibrary_json,
                import_context=import_context,
            )

        if merged.get("title"):
            _cache_set(cache_key, merged, CACHE_TTL)
            return merged

        attempted: list[dict | None] = [ol_result]
        if gb_attempted:
            attempted.append(gb_result)
        if wd_attempted:
            attempted.append(wd_result)
        if any(result is None for result in attempted):
            return {}

        _cache_set(cache_key, {}, NEGATIVE_CACHE_TTL)
        return {}

    def _lookup_isbn_chain(
        self,
        isbn_13: str,
        *,
        import_context: bool,
    ) -> tuple[dict, dict | None, dict | None, dict | None, bool, bool]:
        ol_result = self._lookup_open_library(isbn_13, import_context=import_context)
        merged = _merge_provider_result({}, ol_result, source="open_library")

        gb_attempted = False
        gb_result = None
        if needs_google_books(merged, import_context=import_context):
            gb_attempted = True
            gb_result = self._lookup_google_books(isbn_13, import_context=import_context)
            merged = _merge_provider_result(merged, gb_result, source="google_books")

        wd_attempted = False
        wd_result = None
        if wikidata_enabled() and needs_wikidata(merged, import_context=import_context):
            wd_attempted = True
            wd_result = lookup_isbn_wikidata(
                isbn_13,
                self.session,
                get_fn=self._get_wikidata,
                cache_get=self._cache_get_fn,
                cache_set=self._cache_set_fn,
                import_context=import_context,
            )
            merged = _merge_provider_result(merged, wd_result, source="wikidata")

        if hardcover_enabled() and needs_hardcover(merged, import_context=import_context):
            hc_result = lookup_isbn_hardcover(
                isbn_13,
                self.session,
                post_fn=self._post_hardcover,
                import_context=import_context,
            )
            merged = _merge_provider_result(merged, hc_result, source="hardcover")

        if isbndb_enabled() and needs_isbndb(merged, import_context=import_context):
            idb_result = lookup_isbn_isbndb(
                isbn_13,
                self.session,
                get_fn=self._get_isbndb,
                import_context=import_context,
            )
            merged = _merge_provider_result(merged, idb_result, source="isbndb")

        if needs_archive_cover(merged):
            archive_result = lookup_archive_cover(
                isbn_13,
                self.session,
                get_fn=self._get,
                import_context=import_context,
            )
            merged = _merge_provider_result(merged, archive_result, source="archive_org")

        return merged, ol_result, gb_result, wd_result, gb_attempted, wd_attempted

    def _lookup_isbn_parallel(
        self,
        isbn_13: str,
        *,
        import_context: bool,
    ) -> tuple[dict, dict | None, dict | None, dict | None, bool, bool]:
        candidates: list[dict] = []

        ol_result = self._lookup_open_library(isbn_13, import_context=import_context)
        if ol_result is not None:
            payload = _provider_payload(ol_result)
            if payload:
                candidates.append(payload)

        gb_result = self._lookup_google_books(isbn_13, import_context=import_context)
        if gb_result is not None:
            payload = _provider_payload(gb_result)
            if payload:
                candidates.append(payload)

        wd_result = None
        wd_attempted = False
        if wikidata_enabled():
            wd_attempted = True
            wd_result = lookup_isbn_wikidata(
                isbn_13,
                self.session,
                get_fn=self._get_wikidata,
                cache_get=self._cache_get_fn,
                cache_set=self._cache_set_fn,
                import_context=import_context,
            )
            if wd_result:
                candidates.append(_provider_payload(wd_result))

        if hardcover_enabled():
            hc_result = lookup_isbn_hardcover(
                isbn_13,
                self.session,
                post_fn=self._post_hardcover,
                import_context=import_context,
            )
            if hc_result:
                candidates.append(_provider_payload(hc_result))

        if isbndb_enabled():
            idb_result = lookup_isbn_isbndb(
                isbn_13,
                self.session,
                get_fn=self._get_isbndb,
                import_context=import_context,
            )
            if idb_result:
                candidates.append(_provider_payload(idb_result))

        non_empty = [c for c in candidates if c]
        merged = merge_metadata_best_per_field(*non_empty) if non_empty else {}

        if needs_archive_cover(merged):
            archive_result = lookup_archive_cover(
                isbn_13,
                self.session,
                get_fn=self._get,
                import_context=import_context,
            )
            merged = _merge_provider_result(merged, archive_result, source="archive_org")

        return merged, ol_result, gb_result, wd_result, True, wd_attempted

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

        cover_url = self._open_library_cover(
            isbn_13,
            book_data.get("cover"),
            edition_key=book_data.get("key"),
        )

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
            "source": "open_library",
        }

    def _open_library_work_id(self, book_data: dict) -> str | None:
        works = book_data.get("works") or []
        if works:
            work = works[0]
            if isinstance(work, dict):
                return work.get("key")
            return str(work)
        return None

    def _open_library_cover(
        self,
        isbn_13: str,
        cover: dict | None,
        *,
        edition_key: str | None = None,
    ) -> str | None:
        extra_urls: list[str] = []
        if cover:
            if cover.get("large"):
                extra_urls.append(cover["large"])
            if cover.get("medium"):
                extra_urls.append(cover["medium"])
        return resolve_openlibrary_cover_url(
            edition_olid=edition_key,
            isbn_13=isbn_13,
            extra_urls=extra_urls,
        )

    def _lookup_google_books(
        self,
        isbn_13: str,
        *,
        import_context: bool = False,
    ) -> dict | None:
        url = f"{settings.GOOGLE_BOOKS_BASE_URL.rstrip('/')}/volumes"
        response = self._get(
            url,
            params=_google_books_params({"q": f"isbn:{isbn_13}"}),
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
        published_date = volume_info.get("publishedDate") or ""
        published_year = None
        if published_date:
            year_match = published_date[:4]
            if year_match.isdigit():
                published_year = int(year_match)

        return {
            "title": volume_info.get("title"),
            "authors": volume_info.get("authors", []),
            "pages": volume_info.get("pageCount"),
            "publisher": volume_info.get("publisher"),
            "published_year": published_year,
            "description": volume_info.get("description"),
            "cover_url": image_links.get("thumbnail"),
            "genres": genres,
            "subjects": raw_categories,
            "google_books_id": items[0].get("id"),
            "source": "google_books",
        }

    def search_books(self, query: str, *, limit: int = 10, import_context: bool = False) -> list[dict]:
        query = (query or "").strip()
        if not query:
            return []

        cache_key = metadata_search_cache_key("search", query, limit)
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        results = self._search_open_library(query, limit=limit, import_context=import_context)

        if metadata_lookup_strategy() == "parallel" or needs_more_search_results(results, limit):
            gb_results = self._search_google_books(query, limit=limit, import_context=import_context)
            results = self._merge_search_results(results, gb_results)

        if wikidata_enabled() and (
            metadata_lookup_strategy() == "parallel" or needs_more_search_results(results, limit)
        ):
            wd_results = search_wikidata(
                query,
                self.session,
                limit=limit,
                get_fn=self._get_wikidata,
                cache_get=self._cache_get_fn,
                cache_set=self._cache_set_fn,
                import_context=import_context,
            )
            results = self._merge_search_results(results, wd_results)

        if hardcover_enabled() and (
            metadata_lookup_strategy() == "parallel" or needs_more_search_results(results, limit)
        ):
            hc_results = search_hardcover(
                query,
                self.session,
                limit=limit,
                post_fn=self._post_hardcover,
                import_context=import_context,
            )
            results = self._merge_search_results(results, hc_results)

        _cache_set(cache_key, results, CACHE_TTL if results else NEGATIVE_CACHE_TTL)
        return results

    def _merge_search_results(self, primary: list[dict], secondary: list[dict]) -> list[dict]:
        if not secondary:
            return primary
        seen: set[str] = set()
        merged: list[dict] = []
        for item in primary + secondary:
            key = item.get("isbn_13") or item.get("wikidata_id") or item.get("google_books_id")
            if not key:
                title = (item.get("title") or "").lower()
                authors = "|".join(item.get("authors") or [])
                key = f"{title}|{authors}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

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
            edition_key = doc.get("key")
            cover_url = resolve_openlibrary_cover_url(
                cover_id=cover_id if cover_id and cover_id > 0 else None,
                edition_olid=edition_key,
                isbn_13=isbn_13,
                isbn_10=isbn_10,
            )
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
            params=_google_books_params({"q": query, "maxResults": limit}),
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
