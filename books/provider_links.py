from __future__ import annotations

from books.models import Book


def book_provider_links(book: Book) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []

    if book.openlibrary_work_id:
        work = book.openlibrary_work_id.removeprefix("/works/")
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/works/{work}",
            }
        )
    elif book.openlibrary_edition_key:
        edition = book.openlibrary_edition_key.removeprefix("/books/")
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/books/{edition}",
            }
        )
    elif book.isbn_13:
        links.append(
            {
                "name": "Open Library",
                "url": f"https://openlibrary.org/isbn/{book.isbn_13}",
            }
        )

    if book.google_books_id:
        links.append(
            {
                "name": "Google Books",
                "url": f"https://books.google.com/books?id={book.google_books_id}",
            }
        )

    if book.wikidata_id:
        links.append(
            {
                "name": "Wikidata",
                "url": f"https://www.wikidata.org/wiki/{book.wikidata_id}",
            }
        )

    if book.hardcover_edition_id:
        links.append(
            {
                "name": "Hardcover",
                "url": f"https://hardcover.app/editions/{book.hardcover_edition_id}",
            }
        )

    isbn = book.isbn_13 or book.isbn_10
    if isbn:
        links.append(
            {
                "name": "Amazon",
                "url": f"https://www.amazon.com/s?k={isbn}",
            }
        )
        links.append(
            {
                "name": "Goodreads",
                "url": f"https://www.goodreads.com/search?q={isbn}",
            }
        )

    return links
