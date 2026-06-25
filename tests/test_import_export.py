import csv
import io
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from books.factories import BookFactory
from books.import_export import (
    _parse_goodreads_isbn,
    export_csv,
    export_json,
    import_goodreads_csv,
    import_isbns,
)
from books.models import Book, ImportJob


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
