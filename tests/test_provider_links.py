from urllib.parse import unquote_plus

import pytest

from books.factories import AuthorFactory, BookAuthorFactory, BookFactory
from books.provider_links import book_provider_links


def _by_name(links: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {link["name"]: link for link in links}


@pytest.mark.django_db
class TestBookProviderLinks:
    def test_isbn_book_includes_store_and_free_sources(self):
        book = BookFactory(title="The Trial", isbn_13="9780306406157")
        author = AuthorFactory(name="Franz Kafka")
        BookAuthorFactory(book=book, author=author)

        links = _by_name(book_provider_links(book))

        assert "Amazon" in links
        assert "9780306406157" in links["Amazon"]["url"]
        assert "Goodreads" in links
        assert "Open Library" in links
        assert "/isbn/9780306406157" in links["Open Library"]["url"]
        assert "Project Gutenberg" in links
        assert "The Trial" in unquote_plus(links["Project Gutenberg"]["url"])
        assert "Kafka" in unquote_plus(links["Project Gutenberg"]["url"])
        assert "Internet Archive" in links
        assert "9780306406157" in links["Internet Archive"]["url"]
        assert links["Project Gutenberg"]["kind"] == "free"
        assert links["Internet Archive"]["kind"] == "free"

    def test_title_only_book_gets_search_fallbacks(self):
        book = BookFactory(title="Dune", isbn_13=None, isbn_10=None)
        author = AuthorFactory(name="Frank Herbert")
        BookAuthorFactory(book=book, author=author)

        links = _by_name(book_provider_links(book))

        assert "Open Library" in links
        assert "search?q=" in links["Open Library"]["url"]
        assert "Dune" in unquote_plus(links["Open Library"]["url"])
        assert "Google Books" in links
        assert "Amazon" in links
        assert "Goodreads" in links
        assert "Project Gutenberg" in links
        assert "Internet Archive" in links
        assert "Dune" in unquote_plus(links["Internet Archive"]["url"])
        assert "Herbert" in unquote_plus(links["Internet Archive"]["url"])

    def test_deep_links_when_provider_ids_set(self):
        book = BookFactory(
            title="Neuromancer",
            openlibrary_work_id="/works/OL123W",
            google_books_id="gbabc",
            wikidata_id="Q123",
            hardcover_edition_id="hc-1",
            isbn_13="9780441569595",
        )

        links = _by_name(book_provider_links(book))

        assert links["Open Library"]["url"] == "https://openlibrary.org/works/OL123W"
        assert links["Google Books"]["url"] == "https://books.google.com/books?id=gbabc"
        assert links["Wikidata"]["url"] == "https://www.wikidata.org/wiki/Q123"
        assert links["Hardcover"]["url"] == "https://hardcover.app/editions/hc-1"
        assert "Project Gutenberg" in links
        assert "Internet Archive" in links
