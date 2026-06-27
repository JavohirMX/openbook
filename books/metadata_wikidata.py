"""Wikidata metadata provider (ISBN lookup and title search)."""

from __future__ import annotations

import logging
import re
import time
from typing import Callable

import requests
from django.conf import settings

from books.genre_normalize import normalize_metadata_genres
from books.metadata_cache_keys import metadata_search_cache_key
from books.isbn import normalize_isbn

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
BOOK_INSTANCE_Q = "Q571"

_CACHE_TTL = 60 * 60 * 24 * 30
_NEGATIVE_TTL = 60 * 60


def wikidata_enabled() -> bool:
    return bool(getattr(settings, "METADATA_WIKIDATA_ENABLED", True))


def _wikidata_delay() -> float:
    return float(getattr(settings, "METADATA_WIKIDATA_DELAY_SECONDS", 1.0))


def _commons_image_url(filename: str) -> str | None:
    if not filename:
        return None
    name = filename.replace(" ", "_")
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width=800"


def _parse_entity_labels(entity: dict) -> dict:
    labels = entity.get("labels", {})
    en = labels.get("en", {}).get("value")
    return {"title": en}


def _parse_entity_description(entity: dict) -> str | None:
    descriptions = entity.get("descriptions", {})
    return descriptions.get("en", {}).get("value")


def _claim_values(claims: dict, prop: str) -> list[str]:
    values = []
    for claim in claims.get(prop, []):
        mainsnak = claim.get("mainsnak", {})
        datavalue = mainsnak.get("datavalue", {})
        val = datavalue.get("value")
        if isinstance(val, str):
            values.append(val)
        elif isinstance(val, dict):
            if "id" in val:
                values.append(val["id"])
            elif "text" in val:
                values.append(val["text"])
            elif "amount" in val:
                values.append(str(val["amount"]))
    return values


def _entity_to_metadata(entity: dict, entity_id: str) -> dict:
    claims = entity.get("claims", {})
    title = _parse_entity_labels(entity).get("title")
    description = _parse_entity_description(entity)

    isbn_13 = None
    isbn_10 = None
    for raw in _claim_values(claims, "P212"):
        norm = normalize_isbn(raw)
        if norm and norm.isbn_13:
            isbn_13 = norm.isbn_13
    for raw in _claim_values(claims, "P957"):
        norm = normalize_isbn(raw)
        if norm and norm.isbn_10:
            isbn_10 = norm.isbn_10

    pages = None
    for raw in _claim_values(claims, "P1104"):
        try:
            pages = int(float(raw))
            break
        except (TypeError, ValueError):
            continue

    published_year = None
    for raw in _claim_values(claims, "P577"):
        match = re.search(r"\d{4}", str(raw))
        if match:
            published_year = int(match.group())
            break

    publisher = None
    pub_ids = _claim_values(claims, "P123")
    if pub_ids:
        publisher = pub_ids[0]

    cover_url = None
    for raw in _claim_values(claims, "P18"):
        cover_url = _commons_image_url(raw)
        if cover_url:
            break

    authors: list[str] = []
    author_ids = _claim_values(claims, "P50")[:5]

    genres = normalize_metadata_genres(_claim_values(claims, "P136"))

    result = {
        "title": title,
        "authors": authors,
        "pages": pages,
        "publisher": publisher,
        "published_year": published_year,
        "cover_url": cover_url,
        "description": description,
        "genres": genres,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "wikidata_id": entity_id,
        "source": "wikidata",
    }
    if author_ids:
        result["_wikidata_author_ids"] = author_ids
    return {k: v for k, v in result.items() if v is not None and v != "" and v != []}


def lookup_isbn_wikidata(
    isbn_13: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    cache_get: Callable | None = None,
    cache_set: Callable | None = None,
    import_context: bool = False,
) -> dict | None:
    if not wikidata_enabled():
        return {}

    cache_key = f"metadata:wikidata:isbn:{isbn_13}"
    if cache_get:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

    query = f"""
    SELECT ?item WHERE {{
      ?item wdt:P212 "{isbn_13}" .
    }} LIMIT 1
    """
    entity_id = _sparql_entity_id(query, session, get_fn=get_fn, import_context=import_context)
    if not entity_id:
        if cache_set:
            cache_set(cache_key, {}, _NEGATIVE_TTL)
        return {}

    metadata = fetch_wikidata_entity(
        entity_id, session, get_fn=get_fn, import_context=import_context
    )
    if cache_set:
        cache_set(cache_key, metadata or {}, _CACHE_TTL if metadata else _NEGATIVE_TTL)
    return metadata or {}


def search_wikidata(
    query: str,
    session: requests.Session,
    *,
    limit: int = 10,
    get_fn: Callable[..., requests.Response | None] | None = None,
    cache_get: Callable | None = None,
    cache_set: Callable | None = None,
    import_context: bool = False,
) -> list[dict]:
    if not wikidata_enabled() or not query.strip():
        return []

    cache_key = metadata_search_cache_key("wikidata", query, limit)
    if cache_get:
        cached = cache_get(cache_key)
        if cached is not None:
            return cached

    url = WIKIDATA_API
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "type": "item",
        "limit": limit,
        "format": "json",
    }
    response = _do_get(url, params, session, get_fn=get_fn, import_context=import_context)
    if response is None:
        return []

    results = []
    for item in response.json().get("search", []):
        entity_id = item.get("id")
        if not entity_id:
            continue
        description = item.get("description") or ""
        if description and "book" not in description.lower() and "novel" not in description.lower():
            continue
        meta = {
            "title": item.get("label"),
            "description": description,
            "wikidata_id": entity_id,
            "source": "wikidata",
        }
        results.append(meta)

    if cache_set:
        cache_set(cache_key, results, _CACHE_TTL if results else _NEGATIVE_TTL)
    time.sleep(_wikidata_delay())
    return results


def fetch_wikidata_entity(
    entity_id: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> dict | None:
    if not entity_id:
        return {}

    params = {
        "action": "wbgetentities",
        "ids": entity_id,
        "props": "labels|descriptions|claims",
        "languages": "en",
        "format": "json",
    }
    response = _do_get(WIKIDATA_API, params, session, get_fn=get_fn, import_context=import_context)
    if response is None:
        return None

    entities = response.json().get("entities", {})
    entity = entities.get(entity_id)
    if not entity or entity.get("missing"):
        return {}

    metadata = _entity_to_metadata(entity, entity_id)
    author_ids = metadata.pop("_wikidata_author_ids", [])
    if author_ids:
        author_names = _resolve_author_labels(author_ids, session, get_fn=get_fn, import_context=import_context)
        if author_names:
            metadata["authors"] = author_names
    publisher = metadata.get("publisher")
    if publisher and str(publisher).startswith("Q"):
        pub_labels = _resolve_author_labels(
            [str(publisher)], session, get_fn=get_fn, import_context=import_context
        )
        if pub_labels:
            metadata["publisher"] = pub_labels[0]
    time.sleep(_wikidata_delay())
    return metadata


def _resolve_author_labels(
    entity_ids: list[str],
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> list[str]:
    if not entity_ids:
        return []
    params = {
        "action": "wbgetentities",
        "ids": "|".join(entity_ids[:5]),
        "props": "labels",
        "languages": "en",
        "format": "json",
    }
    response = _do_get(WIKIDATA_API, params, session, get_fn=get_fn, import_context=import_context)
    if response is None:
        return []
    names = []
    for eid, entity in response.json().get("entities", {}).items():
        label = entity.get("labels", {}).get("en", {}).get("value")
        if label:
            names.append(label)
    return names


def _sparql_entity_id(
    query: str,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> str | None:
    response = _do_get(
        WIKIDATA_SPARQL,
        {"query": query, "format": "json"},
        session,
        get_fn=get_fn,
        import_context=import_context,
    )
    if response is None:
        return None
    bindings = response.json().get("results", {}).get("bindings", [])
    if not bindings:
        return None
    item_uri = bindings[0].get("item", {}).get("value", "")
    if "/entity/" in item_uri:
        return item_uri.rsplit("/", 1)[-1]
    return None


def _do_get(
    url: str,
    params: dict,
    session: requests.Session,
    *,
    get_fn: Callable[..., requests.Response | None] | None = None,
    import_context: bool = False,
) -> requests.Response | None:
    if get_fn:
        return get_fn(url, params=params, import_context=import_context)
    try:
        response = session.get(url, params=params, timeout=(5, 15))
        response.raise_for_status()
        return response
    except requests.RequestException as exc:
        log = logger.info if import_context else logger.warning
        log("Wikidata request failed: %s", exc)
        return None
