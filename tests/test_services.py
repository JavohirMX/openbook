import csv
import io
from unittest.mock import patch

import pytest

from books.factories import BookFactory
from books.import_export import import_goodreads_csv
from books.models import Book, BookAuthor
from books.services import attach_authors_to_book


@pytest.mark.django_db
def test_attach_authors_dedupes_exact_duplicate_names():
    book = BookFactory()
    attach_authors_to_book(book, ["Same Author", "Same Author"])
    assert BookAuthor.objects.filter(book=book).count() == 1


@pytest.mark.django_db
def test_attach_authors_dedupes_case_insensitive_names():
    book = BookFactory()
    attach_authors_to_book(book, ["Jane Doe", "jane doe"])
    assert BookAuthor.objects.filter(book=book).count() == 1


@pytest.mark.django_db
def test_attach_authors_preserves_order_for_distinct_authors():
    book = BookFactory()
    attach_authors_to_book(book, ["First Author", "Second Author", "First Author"])
    links = list(BookAuthor.objects.filter(book=book).order_by("position"))
    assert len(links) == 2
    assert links[0].author.name == "First Author"
    assert links[0].position == 1
    assert links[1].author.name == "Second Author"
    assert links[1].position == 2


@pytest.mark.django_db
def test_goodreads_import_with_duplicate_metadata_authors(settings):
    settings.IMPORT_GOODREADS_ENRICH_METADATA = True
    settings.METADATA_IMPORT_DELAY_SECONDS = 0
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "Dup Author Book", "Dup Author", "", '="9780306406157"', "0", "",
        "200", "2020", "Pub", "to-read", "",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "goodreads.csv"

    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.return_value = {
            "title": "Dup Author Book",
            "authors": ["Dup Author", "Dup Author"],
        }
        result = import_goodreads_csv(file)

    assert result.added == 1
    assert result.failed == 0
    book = Book.objects.get(title="Dup Author Book")
    assert BookAuthor.objects.filter(book=book).count() == 1
