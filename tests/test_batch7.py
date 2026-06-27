import csv
import io
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status

from accounts.models import ApiToken, UserProfile
from books.factories import BookFactory
from books.import_export import (
    detect_csv_import_kind,
    import_storygraph_csv,
    preview_storygraph_csv,
)
from books.models import Book, ImportJob, ImportJobKind, ReadingLog, ReadingStatus


STORYGRAPH_HEADER = [
    "Title",
    "Authors",
    "Contributors",
    "ISBN/UID",
    "Format",
    "Read Status",
    "Date Added",
    "Last Date Read",
    "Dates Read",
    "Read Count",
    "Star Rating",
    "Review",
    "Tags",
    "Owned?",
]


def _storygraph_csv(*rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(STORYGRAPH_HEADER)
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


@pytest.mark.django_db
class TestApiTokens:
    def test_create_and_list_tokens_in_settings(self, client, user):
        client.force_login(user)
        response = client.post(
            reverse("web:settings"),
            {"action": "create_token", "label": "Automation"},
        )
        assert response.status_code == 302
        assert ApiToken.objects.filter(user=user, label="Automation").exists()

        page = client.get(reverse("web:settings"))
        assert b"Automation" in page.content
        assert b"API Tokens" in page.content

    def test_revoke_token(self, client, user):
        token = ApiToken.create_for_user(user, label="To revoke")
        client.force_login(user)
        response = client.post(
            reverse("web:settings"),
            {"action": "revoke_token", "token_id": token.pk},
        )
        assert response.status_code == 302
        assert not ApiToken.objects.filter(pk=token.pk).exists()

    def test_last_used_at_updated_on_api_request(self, api_client, user):
        token = ApiToken.create_for_user(user, label="Used")
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        response = api_client.get(reverse("api-stats"))
        assert response.status_code == status.HTTP_200_OK
        token.refresh_from_db()
        assert token.last_used_at is not None


@pytest.mark.django_db
class TestPublicProfile:
    def test_profile_requires_valid_key(self, client, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.embed_enabled = True
        profile.embed_key = "profile-key"
        profile.save()

        ok = client.get(reverse("web:public-profile"), {"key": "profile-key"})
        assert ok.status_code == 200
        assert b"Reading profile" in ok.content

        short = client.get(reverse("web:public-profile-short"), {"key": "profile-key"})
        assert short.status_code == 200

        bad = client.get(reverse("web:public-profile"), {"key": "wrong"})
        assert bad.status_code == 403

    def test_profile_shows_reading_sections(self, client, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.embed_enabled = True
        profile.embed_key = "show-key"
        profile.save()

        reading = BookFactory(title="Active Read")
        log = ReadingLog.objects.get(book=reading)
        log.status = ReadingStatus.READING
        log.save()

        finished = BookFactory(title="Done Book")
        flog = ReadingLog.objects.get(book=finished)
        flog.status = ReadingStatus.FINISHED
        flog.finished_at = flog.updated_at
        flog.save()

        response = client.get(reverse("web:public-profile"), {"key": "show-key"})
        assert b"Active Read" in response.content
        assert b"Done Book" in response.content
        assert b"Quick Stats" in response.content


@pytest.mark.django_db
class TestOpdsFeed:
    def test_opds_requires_auth(self, client):
        response = client.get(reverse("opds-catalog"))
        assert response.status_code == 401

    def test_opds_with_embed_key(self, client, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.embed_enabled = True
        profile.embed_key = "opds-key"
        profile.save()

        want = BookFactory(title="Want Book")
        ReadingLog.objects.filter(book=want).update(status=ReadingStatus.NOT_STARTED)

        read = BookFactory(title="Read Book")
        ReadingLog.objects.filter(book=read).update(
            status=ReadingStatus.FINISHED,
            finished_at=ReadingLog.objects.get(book=read).updated_at,
        )

        response = client.get(reverse("opds-catalog"), {"key": "opds-key"})
        assert response.status_code == 200
        assert response["Content-Type"] == "application/atom+xml;profile=opds-catalog"
        body = response.content.decode()
        assert "Want Book" in body
        assert "Read Book" in body
        assert "atom:entry" in body or "entry" in body

    def test_opds_with_api_token(self, client, user):
        token = ApiToken.create_for_user(user, label="OPDS")
        BookFactory(title="Token Book")
        response = client.get(
            reverse("opds-catalog"),
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )
        assert response.status_code == 200
        assert b"Token Book" in response.content


@pytest.mark.django_db
class TestStoryGraphImport:
    def test_detect_storygraph_csv(self):
        csv_data = _storygraph_csv(
            ["Dune", "Frank Herbert", "", "9780441172719", "paperback", "read", "2024-01-01", "", "", "1", "4.5", "", "sci-fi", ""],
        )
        kind = detect_csv_import_kind(io.BytesIO(csv_data.encode()))
        assert kind == ImportJobKind.STORYGRAPH_CSV

    def test_preview_storygraph_csv(self):
        csv_data = _storygraph_csv(
            ["Dune", "Frank Herbert", "", "9780441172719", "paperback", "read", "2024-01-01", "", "2024/06/01-2024/06/15", "1", "4.5", "Great", "sci-fi", ""],
        )
        preview = preview_storygraph_csv(io.BytesIO(csv_data.encode()))
        assert len(preview) == 1
        assert preview[0]["title"] == "Dune"
        assert preview[0]["status"] == ReadingStatus.FINISHED.value
        assert preview[0]["rating"] == 5

    def test_import_storygraph_csv(self):
        csv_data = _storygraph_csv(
            ["The Hobbit", "J.R.R. Tolkien", "", "", "paperback", "to-read", "2024-02-01", "", "", "0", "0", "", "fantasy", ""],
            ["1984", "George Orwell", "", "9780451524935", "paperback", "currently reading", "2024-03-01", "", "", "0", "3.75", "", "", ""],
        )
        with patch("books.import_export._should_enrich_goodreads_row", return_value=False):
            result = import_storygraph_csv(io.BytesIO(csv_data.encode()))
        assert result.added == 2
        assert Book.objects.filter(title="The Hobbit").exists()
        assert Book.objects.filter(title="1984").exists()
        hobbit_log = ReadingLog.objects.get(book__title="The Hobbit")
        assert hobbit_log.status == ReadingStatus.NOT_STARTED

    def test_storygraph_import_job(self, authenticated_client, user):
        csv_data = _storygraph_csv(
            ["Neuromancer", "William Gibson", "", "", "paperback", "read", "2024-01-01", "2024-05-01", "", "1", "4", "", "", ""],
        )
        upload = io.BytesIO(csv_data.encode())
        upload.name = "storygraph-export.csv"
        response = authenticated_client.post(
            reverse("api-import"),
            {"file": upload},
            format="multipart",
        )
        assert response.status_code == status.HTTP_202_ACCEPTED
        job = ImportJob.objects.get(user=user)
        assert job.kind == ImportJobKind.STORYGRAPH_CSV
        assert job.status == "awaiting_confirmation"
        assert len(job.preview) == 1
