import pytest

from books.metadata_chain import (
    needs_archive_cover,
    needs_google_books,
    needs_hardcover,
    needs_more_search_results,
    needs_wikidata,
)


class TestNeedsGoogleBooks:
    def test_import_skips_when_open_library_complete(self):
        merged = {
            "title": "Dune",
            "authors": ["Frank Herbert"],
            "cover_url": "https://covers.openlibrary.org/b/isbn/9780441172719-L.jpg",
        }
        assert needs_google_books(merged, import_context=True) is False

    def test_import_needs_when_missing_title(self):
        assert needs_google_books({}, import_context=True) is True

    def test_import_needs_when_missing_authors(self):
        merged = {"title": "Dune", "cover_url": "https://example.com/cover.jpg"}
        assert needs_google_books(merged, import_context=True) is True

    def test_import_needs_when_missing_cover_and_pages(self):
        merged = {"title": "Dune", "authors": ["Frank Herbert"]}
        assert needs_google_books(merged, import_context=True) is True

    def test_interactive_needs_description(self):
        merged = {
            "title": "Dune",
            "authors": ["Frank Herbert"],
            "cover_url": "https://example.com/cover.jpg",
        }
        assert needs_google_books(merged, import_context=False) is True

    def test_interactive_skips_when_description_present(self):
        merged = {
            "title": "Dune",
            "authors": ["Frank Herbert"],
            "cover_url": "https://example.com/cover.jpg",
            "description": "A desert planet novel.",
            "published_year": 1965,
            "publisher": "Ace",
        }
        assert needs_google_books(merged, import_context=False) is False


class TestNeedsWikidata:
    def test_import_only_when_missing_title(self):
        merged = {"title": "Dune", "authors": ["Frank Herbert"]}
        assert needs_wikidata(merged, import_context=True) is False

    def test_import_when_missing_title(self):
        assert needs_wikidata({}, import_context=True) is True

    def test_interactive_when_sparse(self):
        merged = {"title": "Dune", "authors": ["Frank Herbert"]}
        assert needs_wikidata(merged, import_context=False) is True

    def test_interactive_skips_when_rich(self):
        merged = {
            "title": "Dune",
            "authors": ["Frank Herbert"],
            "cover_url": "https://example.com/cover.jpg",
            "genres": ["Science Fiction"],
            "description": "Epic.",
        }
        assert needs_wikidata(merged, import_context=False) is False


class TestNeedsMoreSearchResults:
    def test_enough_open_library_results(self):
        results = [{"title": f"Book {index}"} for index in range(5)]
        assert needs_more_search_results(results, limit=10) is False

    def test_sparse_open_library_results(self):
        results = [{"title": "Only Hit"}]
        assert needs_more_search_results(results, limit=10) is True

    def test_ignores_results_without_title(self):
        results = [{"authors": ["Someone"]}]
        assert needs_more_search_results(results, limit=10) is True

    @pytest.mark.parametrize("limit", [1, 2, 3])
    def test_threshold_respects_limit(self, limit):
        results = [{"title": f"Book {index}"} for index in range(limit)]
        assert needs_more_search_results(results, limit=limit) is False


class TestNeedsHardcover:
    def test_needs_when_missing_cover(self):
        merged = {"title": "Dune", "series_name": "Dune Chronicles"}
        assert needs_hardcover(merged, import_context=True) is True

    def test_needs_when_missing_series(self):
        merged = {"title": "Dune", "cover_url": "https://example.com/cover.jpg"}
        assert needs_hardcover(merged, import_context=True) is True


class TestNeedsArchiveCover:
    def test_needs_when_title_without_cover(self):
        assert needs_archive_cover({"title": "Dune"}) is True

    def test_skips_when_cover_present(self):
        assert needs_archive_cover({"title": "Dune", "cover_url": "https://example.com/c.jpg"}) is False
