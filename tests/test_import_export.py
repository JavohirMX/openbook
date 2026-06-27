import csv
import io
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from books.factories import BookFactory
from books.import_export import (
    _create_book_from_data,
    _parse_goodreads_isbn,
    export_csv,
    export_json,
    import_goodreads_csv,
    import_isbns,
)
from books.models import Book, ImportJob


@pytest.mark.django_db
def test_create_book_from_data_persists_provider_ids():
    book = _create_book_from_data(
        {"title": "Imported Book", "author": "Author"},
        {
            "openlibrary_work_id": "/works/OL1W",
            "google_books_id": "gb123",
            "wikidata_id": "Q1",
            "source_summary": "open_library+google_books",
        },
    )
    assert book.openlibrary_work_id == "/works/OL1W"
    assert book.google_books_id == "gb123"
    assert book.wikidata_id == "Q1"
    assert book.metadata_source_summary == "open_library+google_books"


@pytest.mark.django_db
def test_import_isbns_skips_duplicates():
    BookFactory(isbn_13="9780141439518", title="Existing")
    with patch("books.import_export.MetadataService") as mock_svc:
        mock_svc.return_value.lookup_isbn.return_value = {
            "title": "New Title",
            "authors": ["Author"],
        }
        result = import_isbns(["9780141439518", "9780000000001"])
    assert result.skipped >= 1


@pytest.mark.django_db
def test_import_isbns_adds_book():
    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.return_value = {
            "title": "Imported Book",
            "authors": ["Test Author"],
            "pages": 200,
        }
        result = import_isbns(["9780143127550"])
    assert result.added == 1
    assert Book.objects.filter(title="Imported Book").exists()


@pytest.mark.django_db
def test_api_import_isbns(authenticated_client, user):
    response = authenticated_client.post(
        reverse("api-import"),
        {"isbns": ["9780143127551"]},
        format="json",
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()["data"]
    assert data["status"] == "pending"
    assert ImportJob.objects.filter(user=user, kind="isbns").exists()


@pytest.mark.django_db
def test_parse_goodreads_isbn_empty_cells():
    assert _parse_goodreads_isbn('=""') is None
    assert _parse_goodreads_isbn('=""""') is None
    assert _parse_goodreads_isbn('="9781101904220"') == "9781101904220"


@pytest.mark.django_db
def test_goodreads_import_empty_isbns_not_treated_as_duplicates():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "Sophie's World", "Jostein Gaarder", '=""', '=""', "0", "",
        "500", "1991", "Pub", "to-read", "",
    ])
    writer.writerow([
        "Norwegian Wood", "Haruki Murakami", '=""', '=""', "4", "",
        "296", "2000", "Vintage", "read", "",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "goodreads.csv"
    result = import_goodreads_csv(file)
    assert result.added == 2
    assert result.skipped == 0
    assert Book.objects.filter(title="Sophie's World").exists()
    assert Book.objects.filter(title="Norwegian Wood").exists()


@pytest.mark.django_db
def test_goodreads_import_dates_and_additional_authors():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "Additional Authors", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
        "Date Read", "Date Added",
    ])
    writer.writerow([
        "The Way of Kings", "Brandon Sanderson", "Illustrator Name",
        '=""', '=""', "5", "Epic",
        "1000", "2010", "Tor", "read", "",
        "2024/06/15", "2023/01/10",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "goodreads.csv"
    result = import_goodreads_csv(file)
    assert result.added == 1
    book = Book.objects.get(title="The Way of Kings")
    author_names = list(book.authors.order_by("book_authors__position").values_list("name", flat=True))
    assert author_names == ["Brandon Sanderson", "Illustrator Name"]
    log = book.reading_log
    assert log.finished_at.isoformat() == "2024-06-15"
    assert log.read_count == 1
    book.refresh_from_db()
    from django.utils import timezone as tz

    assert tz.localtime(book.created_at).date().isoformat() == "2023-01-10"


@pytest.mark.django_db
def test_goodreads_export_includes_dates_and_additional_authors():
    from books.factories import BookFactory
    from books.models import Author, BookAuthor, ReadingLog, ReadingStatus

    book = BookFactory(title="Export Dates", isbn_13="9781111111111")
    a1 = Author.objects.create(name="Primary Author")
    a2 = Author.objects.create(name="Co Author")
    BookAuthor.objects.create(book=book, author=a1, position=0)
    BookAuthor.objects.create(book=book, author=a2, position=1)
    log = book.reading_log
    log.status = ReadingStatus.FINISHED
    log.finished_at = __import__("datetime").date(2024, 3, 20)
    log.save()
    Book.objects.filter(pk=book.pk).update(
        created_at=__import__("datetime").datetime(2022, 5, 1, 12, 0, 0)
    )
    csv_content = export_csv()
    assert "Co Author" in csv_content
    assert "2024/03/20" in csv_content
    assert "2022/05/01" in csv_content


@pytest.mark.django_db
def test_goodreads_csv_round_trip():
    BookFactory(title="Round Trip", isbn_13="9781234567890")
    csv_content = export_csv()
    assert "Round Trip" in csv_content

    initial_count = Book.objects.count()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "Round Trip", "Author", '="1234567890"', '="9781234567890"', "4", "Great",
        "300", "2020", "Pub", "read", "Favourites",
    ])
    file = io.BytesIO(output.getvalue().encode("utf-8"))
    file.name = "export.csv"
    result = import_goodreads_csv(file)
    assert result.skipped >= 1
    assert Book.objects.count() == initial_count


@pytest.mark.django_db
def test_export_json_structure():
    BookFactory(title="Export Me")
    data = export_json()
    assert "books" in data
    assert len(data["books"]) == 1
    assert data["books"][0]["title"] == "Export Me"


@pytest.mark.django_db
def test_api_export_json(authenticated_client):
    BookFactory(title="API Export")
    response = authenticated_client.get(reverse("api-export"), {"format": "json"})
    assert response.status_code == status.HTTP_200_OK
    assert b"API Export" in response.content
