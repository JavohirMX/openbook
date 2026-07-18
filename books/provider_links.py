from __future__ import annotations

from urllib.parse import quote_plus

from books.models import Book


def _author_names(book: Book, *, limit: int = 2) -> str:
    names = [a.name for a in book.authors.all()[:limit] if a.name]
    return " ".join(names)


def _title_author_query(book: Book) -> str:
    parts = [book.title or "", _author_names(book)]
    return " ".join(p.strip() for p in parts if p and p.strip()).strip()


def _isbn(book: Book) -> str:
    return (book.isbn_13 or book.isbn_10 or "").strip()


def book_provider_links(book: Book) -> list[dict[str, str]]:
    """Build outbound catalog, store, and free-library search links for a book.

    Add new providers here; the Find online UI and provider-links API both
    consume this list.
    """
    links: list[dict[str, str]] = []
    isbn = _isbn(book)
    search_q = _title_author_query(book)

    if book.openlibrary_work_id:
        work = book.openlibrary_work_id.removeprefix("/works/")
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/works/{work}",
                "kind": "catalog",
            }
        )
    elif book.openlibrary_edition_key:
        edition = book.openlibrary_edition_key.removeprefix("/books/")
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/books/{edition}",
                "kind": "catalog",
            }
        )
    elif isbn:
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/isbn/{isbn}",
                "kind": "catalog",
            }
        )
    elif search_q:
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/search?q={quote_plus(search_q)}",
                "kind": "catalog",
            }
        )

    if book.google_books_id:
        links.append(
            {
                "name": "Google Books",
                "url": f"https://books.google.com/books?id={book.google_books_id}",
                "kind": "catalog",
            }
        )
    elif isbn:
        links.append(
            {
                "name": "Google Books",
                "url": f"https://www.google.com/search?tbm=bks&q={quote_plus(isbn)}",
                "kind": "catalog",
            }
        )
    elif search_q:
        links.append(
            {
                "name": "Google Books",
                "url": f"https://www.google.com/search?tbm=bks&q={quote_plus(search_q)}",
                "kind": "catalog",
            }
        )

    if book.wikidata_id:
        links.append(
            {
                "name": "Wikidata",
                "url": f"https://www.wikidata.org/wiki/{book.wikidata_id}",
                "kind": "catalog",
            }
        )

    if book.hardcover_edition_id:
        links.append(
            {
                "name": "Hardcover",
                "url": f"https://hardcover.app/editions/{book.hardcover_edition_id}",
                "kind": "catalog",
            }
        )

    store_q = isbn or search_q
    if store_q:
        links.append(
            {
                "name": "Amazon",
                "url": f"https://www.amazon.com/s?k={quote_plus(store_q)}",
                "kind": "store",
            }
        )
        links.append(
            {
                "name": "Goodreads",
                "url": f"https://www.goodreads.com/search?q={quote_plus(store_q)}",
                "kind": "store",
            }
        )

    if search_q:
        links.append(
            {
                "name": "Project Gutenberg",
                "url": f"https://www.gutenberg.org/ebooks/search/?query={quote_plus(search_q)}",
                "kind": "free",
            }
        )

    archive_q = isbn or search_q
    if archive_q:
        links.append(
            {
                "name": "Internet Archive",
                "url": f"https://archive.org/search?query={quote_plus(archive_q)}",
                "kind": "free",
            }
        )

    links.append(
        {
            "name": "WeLib",
            "url": f"https://welib.org/search?q={quote_plus(search_q)}",
            "kind": "free",
            
        }
    )
    
    links.append(
        {
            "name": "oceanofpdf",
            "url": f"https://oceanofpdf.com/?s={quote_plus(search_q)}",
            "kind": "free",
        }
    )
    
    return links
