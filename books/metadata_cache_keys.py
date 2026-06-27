"""Memcached-safe cache key builders for metadata lookups."""

from __future__ import annotations

import hashlib
import re

_UNSAFE_KEY_CHARS = re.compile(r"[^\w.-]+")


def metadata_search_cache_key(provider: str, query: str, limit: int) -> str:
    """Hash free-text search queries so keys are safe for memcached and DatabaseCache."""
    normalized = query.strip().lower()
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    safe_provider = _UNSAFE_KEY_CHARS.sub("-", provider.strip().lower()) or "search"
    return f"metadata:{safe_provider}-search:{digest}:{limit}"
