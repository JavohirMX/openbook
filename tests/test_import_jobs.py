import csv
import io
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status

from books.factories import BookFactory
from books.import_export import import_isbns
from books.import_jobs import confirm_csv_job, create_csv_preview_job, create_isbn_job
from books.models import Book, ImportJob, ImportJobStatus


@pytest.mark.django_db
def test_create_isbn_job():
    from accounts.factories import UserFactory

    user = UserFactory()
    job = create_isbn_job(user, ["9780143127550", "9780143127551"])
    assert job.status == ImportJobStatus.PENDING
    assert job.progress_total == 2
    assert len(job.isbns) == 2


@pytest.mark.django_db
def test_process_isbn_job(user):
    job = create_isbn_job(user, ["9780143127550"])
    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.return_value = {
            "title": "Worker Import",
            "authors": ["Author"],
        }
        call_command("process_import_jobs")
    job.refresh_from_db()
    assert job.status == ImportJobStatus.COMPLETED
    assert job.result["added"] == 1
    assert Book.objects.filter(title="Worker Import").exists()


@pytest.mark.django_db
def test_csv_preview_and_confirm_job(user):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "CSV Job Book", "Author", "", '="9780143127552"', "0", "",
        "200", "2020", "Pub", "to-read", "",
    ])
    uploaded = io.BytesIO(output.getvalue().encode("utf-8"))
    uploaded.name = "goodreads.csv"

    job = create_csv_preview_job(user, uploaded)
    assert job.status == ImportJobStatus.AWAITING_CONFIRMATION
    assert len(job.preview) == 1
    assert job.csv_file

    confirm_csv_job(job)
    job.refresh_from_db()
    assert job.status == ImportJobStatus.PENDING

    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.return_value = {
            "title": "CSV Job Book",
            "authors": ["Author"],
        }
        call_command("process_import_jobs")

    job.refresh_from_db()
    assert job.status == ImportJobStatus.COMPLETED
    assert job.result["added"] == 1


@pytest.mark.django_db
def test_api_import_returns_202_and_poll(authenticated_client, user):
    response = authenticated_client.post(
        reverse("api-import"),
        {"isbns": ["9780143127553"]},
        format="json",
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()["data"]
    job = ImportJob.objects.get(pk=data["id"])
    assert job.user == user
    assert "status_url" in data

    detail = authenticated_client.get(reverse("api-import-job-detail", kwargs={"pk": job.id}))
    assert detail.status_code == status.HTTP_200_OK
    assert detail.json()["data"]["status"] == ImportJobStatus.PENDING


@pytest.mark.django_db
def test_api_import_job_completes(authenticated_client, user):
    job = create_isbn_job(user, ["9780143127554"])
    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.return_value = {
            "title": "API Async Import",
            "authors": ["Someone"],
        }
        call_command("process_import_jobs")

    response = authenticated_client.get(reverse("api-import-job-detail", kwargs={"pk": job.id}))
    assert response.status_code == status.HTTP_200_OK
    body = response.json()["data"]
    assert body["status"] == ImportJobStatus.COMPLETED
    assert body["result"]["added"] == 1


@pytest.mark.django_db
def test_import_isbn_partial_progress_on_failure():
    calls = {"n": 0}

    def lookup(isbn, import_context=False):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("lookup failed")
        return {"title": f"Book {calls['n']}", "authors": ["A"]}

    with patch("books.import_export.MetadataService") as mock_cls:
        mock_cls.return_value.lookup_isbn.side_effect = lookup
        result = import_isbns(["9780141439518", "9780743273565", "9780007523160"])

    assert result.added == 2
    assert result.failed == 1
    assert Book.objects.count() == 2


@pytest.mark.django_db
def test_import_job_detail_requires_owner(api_client, user):
    from accounts.factories import UserFactory

    other = UserFactory()
    job = create_isbn_job(other, ["9780143127557"])
    api_client.force_authenticate(user=user)
    response = api_client.get(reverse("api-import-job-detail", kwargs={"pk": job.id}))
    assert response.status_code == status.HTTP_404_NOT_FOUND
