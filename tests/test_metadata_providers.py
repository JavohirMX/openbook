from unittest.mock import MagicMock, patch

import pytest

from books.metadata_openlibrary import fetch_edition, fetch_work, hydrate_candidate
from books.metadata_wikidata import fetch_wikidata_entity, lookup_isbn_wikidata, search_wikidata


@pytest.fixture
def session():
    return MagicMock()


def test_fetch_work_parses_subjects(session):
    def get_fn(url, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "title": "Dune",
            "subjects": ["Science fiction", "Adventure"],
            "covers": [12345],
            "first_publish_date": "1965",
        }
        return response

    with patch(
        "books.metadata_openlibrary.resolve_openlibrary_cover_url",
        return_value="https://covers.openlibrary.org/b/id/12345-L.jpg",
    ):
        result = fetch_work("/works/OL123W", session, get_fn=get_fn)
    assert result["title"] == "Dune"
    assert "Science Fiction" in result["genres"]
    assert result["cover_url"] == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert result["published_year"] == "1965"


def test_fetch_work_skips_negative_cover_id(session):
    def get_fn(url, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "title": "No Cover Work",
            "covers": [-1],
        }
        return response

    with patch("books.metadata_openlibrary.resolve_openlibrary_cover_url") as mock_resolve:
        result = fetch_work("/works/OL999W", session, get_fn=get_fn)

    assert result.get("cover_url") is None
    mock_resolve.assert_not_called()


def test_fetch_edition_parses_isbn(session):
    def get_fn(url, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "title": "Edition Title",
            "number_of_pages": 300,
            "publishers": ["Ace Books"],
            "isbn_13": ["9780143127741"],
            "isbn_10": ["0143127748"],
            "works": [{"key": "/works/OL893479W"}],
        }
        return response

    result = fetch_edition("/books/OL456M", session, get_fn=get_fn)
    assert result["isbn_13"] == "9780143127741"
    assert result["pages"] == 300
    assert result["openlibrary_work_id"] == "/works/OL893479W"


def test_hydrate_candidate_merges_edition_and_work(session):
    calls = []

    def get_fn(url, **kwargs):
        calls.append(url)
        response = MagicMock()
        if "works" in url:
            response.json.return_value = {
                "title": "Work Title",
                "subjects": ["Fantasy"],
                "covers": [99],
            }
        else:
            response.json.return_value = {
                "title": "Edition Title",
                "number_of_pages": 250,
                "openlibrary_edition_key": "/books/OL1M",
                "works": [{"key": "/works/OL2W"}],
            }
        return response

    base = {"title": "Sparse", "openlibrary_edition_key": "/books/OL1M", "source": "open_library"}
    result = hydrate_candidate(base, session, get_fn=get_fn)
    assert result.get("pages") == 250
    assert len(calls) >= 1


def test_lookup_isbn_wikidata(session):
    entity_id = None

    def get_fn(url, params=None, **kwargs):
        response = MagicMock()
        if "sparql" in url:
            response.json.return_value = {
                "results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q123"}}]}
            }
            return response
        response.json.return_value = {
            "entities": {
                "Q123": {
                    "labels": {"en": {"value": "Test Book"}},
                    "descriptions": {"en": {"value": "A novel"}},
                    "claims": {
                        "P212": [{"mainsnak": {"datavalue": {"value": "9780143127741"}}}],
                    },
                }
            }
        }
        return response

    with patch("books.metadata_wikidata.wikidata_enabled", return_value=True):
        result = lookup_isbn_wikidata("9780143127741", session, get_fn=get_fn)
    assert result["title"] == "Test Book"
    assert result["isbn_13"] == "9780143127741"
    assert result["wikidata_id"] == "Q123"


def test_search_wikidata_filters(session):
    def get_fn(url, params=None, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "search": [
                {"id": "Q1", "label": "Real Book", "description": "science fiction book"},
                {"id": "Q2", "label": "Not Relevant", "description": "city in France"},
            ]
        }
        return response

    with patch("books.metadata_wikidata.wikidata_enabled", return_value=True):
        with patch("books.metadata_wikidata.time.sleep"):
            results = search_wikidata("Dune Herbert", session, get_fn=get_fn, limit=5)
    assert len(results) == 1
    assert results[0]["wikidata_id"] == "Q1"


def test_fetch_wikidata_entity_resolves_publisher_label(session):
    def get_fn(url, params=None, **kwargs):
        response = MagicMock()
        if params and params.get("props") == "labels":
            response.json.return_value = {
                "entities": {"Q12345": {"labels": {"en": {"value": "Ace Books"}}}}
            }
        else:
            response.json.return_value = {
                "entities": {
                    "Q999": {
                        "labels": {"en": {"value": "Test Book"}},
                        "descriptions": {},
                        "claims": {
                            "P123": [{"mainsnak": {"datavalue": {"value": "Q12345"}}}],
                        },
                    }
                }
            }
        return response

    with patch("books.metadata_wikidata.wikidata_enabled", return_value=True):
        with patch("books.metadata_wikidata.time.sleep"):
            result = fetch_wikidata_entity("Q999", session, get_fn=get_fn)
    assert result["publisher"] == "Ace Books"


def test_lookup_isbn_hardcover(session):
    def post_fn(url, json=None, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "data": {
                "editions": [
                    {
                        "id": 42,
                        "title": "Dune",
                        "isbn_13": "9780441172719",
                        "pages": 412,
                        "publisher": {"name": "Ace"},
                        "book": {
                            "description": "Desert planet.",
                            "contributions": [{"author": {"name": "Frank Herbert"}}],
                            "featured_series": {"series": {"name": "Dune"}, "position": 1},
                        },
                        "cached_image": {"url": "https://example.com/cover.jpg"},
                    }
                ]
            }
        }
        return response

    with patch("books.metadata_hardcover.hardcover_enabled", return_value=True):
        from books.metadata_hardcover import lookup_isbn_hardcover

        result = lookup_isbn_hardcover(
            "9780441172719",
            session,
            post_fn=post_fn,
        )
    assert result["title"] == "Dune"
    assert result["series_name"] == "Dune"
    assert result["hardcover_edition_id"] == "42"


def test_lookup_archive_cover(session):
    def get_fn(url, params=None, **kwargs):
        response = MagicMock()
        response.json.return_value = {
            "response": {"docs": [{"identifier": "dune1965"}]}
        }
        return response

    with patch("books.metadata_archive.time.sleep"):
        from books.metadata_archive import lookup_archive_cover

        result = lookup_archive_cover("9780441172719", session, get_fn=get_fn)
    assert "archive.org/services/img/dune1965" in result["cover_url"]
