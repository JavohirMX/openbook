import pytest

from books.metadata_cache_keys import metadata_search_cache_key


def test_search_cache_key_is_stable_and_memcached_safe():
    query = "Hooked: How to Build Habit-Forming Products Nir Eyal"
    key_a = metadata_search_cache_key("wikidata", query, 5)
    key_b = metadata_search_cache_key("wikidata", query, 5)
    key_c = metadata_search_cache_key("wikidata", query.upper(), 5)

    assert key_a == key_b == key_c
    assert " " not in key_a
    assert "hooked" not in key_a
    assert key_a.startswith("metadata:wikidata-search:")
    assert key_a.endswith(":5")


def test_search_cache_key_differs_by_limit():
    query = "Dune Frank Herbert"
    assert metadata_search_cache_key("search", query, 5) != metadata_search_cache_key("search", query, 10)
