import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status

from accounts.factories import UserFactory
from books.factories import BookAuthorFactory, BookFactory, ReadingLogFactory, ShelfFactory
from books.import_jobs import create_isbn_job, run_import_job
from books.library_maintenance import find_duplicate_groups, merge_books
from books.models import Book, ImportJobStatus, ReadingStatus, WebhookEndpoint
from books.reading_service import update_reading_log
from books.webhooks import (
    WEBHOOK_EVENT_IMPORT_COMPLETED,
    WEBHOOK_EVENT_READING_STATUS_CHANGED,
    deliver_webhook,
    emit_event,
    sign_payload,
)


@pytest.mark.django_db
def test_sign_payload_hmac_sha256():
    body = b'{"event":"test"}'
    signature = sign_payload("secret-key", body)
    expected = hmac.new(b"secret-key", body, hashlib.sha256).hexdigest()
    assert signature == f"sha256={expected}"


@pytest.mark.django_db
def test_deliver_webhook_retries_until_success():
    endpoint = WebhookEndpoint.objects.create(
        url="https://example.com/hook",
        secret="test-secret",
        events=[WEBHOOK_EVENT_READING_STATUS_CHANGED],
    )
    payload = {"event": WEBHOOK_EVENT_READING_STATUS_CHANGED, "data": {}}

    responses = [MagicMock(status_code=500), MagicMock(status_code=204)]
    with patch("books.webhooks.requests.post", side_effect=responses) as post:
        with patch("books.webhooks.time.sleep"):
            assert deliver_webhook(endpoint, WEBHOOK_EVENT_READING_STATUS_CHANGED, payload) is True
    assert post.call_count == 2
    headers = post.call_args.kwargs["headers"]
    assert headers["X-Openbook-Event"] == WEBHOOK_EVENT_READING_STATUS_CHANGED
    assert headers["X-Openbook-Signature"].startswith("sha256=")


@pytest.mark.django_db
def test_emit_event_only_targets_subscribed_endpoints():
    WebhookEndpoint.objects.create(
        url="https://example.com/a",
        secret="s1",
        events=[WEBHOOK_EVENT_READING_STATUS_CHANGED],
    )
    WebhookEndpoint.objects.create(
        url="https://example.com/b",
        secret="s2",
        events=[WEBHOOK_EVENT_IMPORT_COMPLETED],
        enabled=False,
    )
    with patch("books.webhooks.deliver_webhook", return_value=True) as deliver:
        count = emit_event(WEBHOOK_EVENT_READING_STATUS_CHANGED, {"book_id": "x"})
    assert count == 1
    deliver.assert_called_once()


@pytest.mark.django_db
def test_reading_status_change_emits_webhook():
    book = BookFactory()
    log = ReadingLogFactory(book=book, status=ReadingStatus.NOT_STARTED)
    with patch("books.webhooks.emit_reading_status_changed") as emit:
        update_reading_log(log, {"status": ReadingStatus.READING})
    emit.assert_called_once()


@pytest.mark.django_db
def test_import_completed_emits_webhook(user):
    with patch("books.import_export.import_isbns") as import_isbns:
        from books.import_export import ImportResult

        import_isbns.return_value = ImportResult()
        job = create_isbn_job(user, ["9780143127550"])
    with patch("books.webhooks.emit_import_completed") as emit:
        run_import_job(job)
    emit.assert_called_once()
    job.refresh_from_db()
    assert job.status == ImportJobStatus.COMPLETED


@pytest.mark.django_db
def test_webhook_api_crud(authenticated_client):
    url = reverse("webhook-list")
    create_resp = authenticated_client.post(
        url,
        {
            "url": "https://example.com/hooks/openbook",
            "events": [WEBHOOK_EVENT_READING_STATUS_CHANGED, WEBHOOK_EVENT_IMPORT_COMPLETED],
        },
        format="json",
    )
    assert create_resp.status_code == status.HTTP_201_CREATED
    webhook_id = create_resp.json()["data"]["id"]

    list_resp = authenticated_client.get(url)
    assert list_resp.status_code == status.HTTP_200_OK
    assert len(list_resp.json()["data"]) == 1

    patch_resp = authenticated_client.patch(
        reverse("webhook-detail", kwargs={"pk": webhook_id}),
        {"enabled": False},
        format="json",
    )
    assert patch_resp.status_code == status.HTTP_200_OK
    assert patch_resp.json()["data"]["enabled"] is False

    delete_resp = authenticated_client.delete(reverse("webhook-detail", kwargs={"pk": webhook_id}))
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
def test_find_duplicate_groups_by_title_author():
    title = "Duplicate Title"
    author_name = "Same Author"
    title_a = BookFactory(title=title, isbn_13=None, isbn_10=None)
    BookAuthorFactory(book=title_a, author__name=author_name)
    title_b = BookFactory(title=title, isbn_13=None, isbn_10=None)
    BookAuthorFactory(book=title_b, author__name=author_name)

    groups = find_duplicate_groups()
    group_book_sets = [{book.pk for book in group.books} for group in groups]
    assert {title_a.pk, title_b.pk} in group_book_sets


@pytest.mark.django_db
def test_merge_books_combines_metadata_and_soft_deletes_source():
    keeper = BookFactory(title="Keeper", pages=100)
    duplicate = BookFactory(title="Duplicate", pages=None, publisher="Pub Co")
    BookAuthorFactory(book=duplicate, author__name="Extra Author")
    shelf = ShelfFactory()
    duplicate.bookshelf_items.create(shelf=shelf)

    merge_books(keeper.pk, [duplicate.pk])

    keeper.refresh_from_db()
    duplicate.refresh_from_db()
    assert keeper.publisher == "Pub Co"
    assert keeper.authors.filter(name="Extra Author").exists()
    assert keeper.bookshelf_items.filter(shelf=shelf).exists()
    assert duplicate.deleted_at is not None


@pytest.mark.django_db
def test_books_bulk_soft_delete(logged_in_client):
    books = [BookFactory() for _ in range(2)]
    response = logged_in_client.post(
        reverse("web:books-bulk"),
        {
            "bulk_action": "soft_delete",
            "book_ids": [str(book.pk) for book in books],
        },
    )
    assert response.status_code == 302
    assert Book.objects.filter(pk__in=[b.pk for b in books]).count() == 0
    assert Book.all_objects.filter(pk__in=[b.pk for b in books], deleted_at__isnull=False).count() == 2


@pytest.mark.django_db
def test_books_bulk_set_status(logged_in_client):
    book = BookFactory()
    response = logged_in_client.post(
        reverse("web:books-bulk"),
        {
            "bulk_action": "set_status",
            "status": ReadingStatus.READING,
            "book_ids": [str(book.pk)],
        },
    )
    assert response.status_code == 302
    book.reading_log.refresh_from_db()
    assert book.reading_log.status == ReadingStatus.READING


@pytest.mark.django_db
def test_books_bulk_add_shelf(logged_in_client):
    book = BookFactory()
    shelf = ShelfFactory()
    response = logged_in_client.post(
        reverse("web:books-bulk"),
        {
            "bulk_action": "add_shelf",
            "shelf_id": shelf.pk,
            "book_ids": [str(book.pk)],
        },
    )
    assert response.status_code == 302
    assert book.bookshelf_items.filter(shelf=shelf).exists()


@pytest.mark.django_db
def test_import_backfill_api(authenticated_client, user):
    book = BookFactory(isbn_13="9780143127551", cover_url=None, pages=None)
    response = authenticated_client.post(
        reverse("api-import-backfill"),
        {"book_ids": [str(book.pk)]},
        format="json",
    )
    assert response.status_code == status.HTTP_202_ACCEPTED
    body = response.json()["data"]
    assert body["kind"] == "metadata_backfill"
    assert body["progress_total"] == 1


@pytest.mark.django_db
def test_export_library_command(tmp_path):
    BookFactory(title="Export Me")
    output = tmp_path / "library.json"
    call_command("export_library", "--output", str(output), "--format", "json")
    data = json.loads(output.read_text(encoding="utf-8"))
    assert any(item.get("title") == "Export Me" for item in data["books"])


@pytest.fixture
def logged_in_client(client, db):
    user = UserFactory(email="batch5@example.com", password="password123")
    client.login(username=user.email, password="password123")
    return client
