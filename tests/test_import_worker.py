from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.factories import UserFactory
from books.import_jobs import create_isbn_job
from books.import_worker import (
    drain_pending_jobs,
    reclaim_stale_running_jobs,
    schedule_import_processing,
)
from books.models import Book, ImportJobStatus


def _mock_metadata():
    return patch(
        "books.import_export.MetadataService",
        return_value=MagicMock(
            lookup_isbn=MagicMock(
                return_value={"title": "Auto Import", "authors": ["Author"]},
            ),
        ),
    )


@pytest.fixture
def web_user(db):
    return UserFactory(email="web@example.com", password="password123")


@pytest.fixture
def logged_in_client(client, web_user):
    client.login(username="web@example.com", password="password123")
    return client


@pytest.mark.django_db
def test_drain_pending_jobs_completes_job(user):
    job = create_isbn_job(user, ["9780143127558"])
    with _mock_metadata():
        drain_pending_jobs()
    job.refresh_from_db()
    assert job.status == ImportJobStatus.COMPLETED
    assert job.result["added"] == 1
    assert Book.objects.filter(title="Auto Import").exists()


@pytest.mark.django_db
@override_settings(IMPORT_JOB_AUTO_PROCESS=False)
def test_schedule_respects_auto_process_setting(user):
    create_isbn_job(user, ["9780143127559"])
    with patch("books.import_worker.threading.Thread") as mock_thread:
        assert schedule_import_processing() is False
        mock_thread.assert_not_called()


@pytest.mark.django_db
@override_settings(IMPORT_JOB_AUTO_PROCESS=False)
def test_schedule_force_bypasses_auto_process_setting():
    with patch("books.import_worker.threading.Thread") as mock_thread:
        mock_thread.return_value.is_alive.return_value = False
        assert schedule_import_processing(force=True) is True
        mock_thread.assert_called_once()


@pytest.mark.django_db
def test_schedule_starts_only_one_drain_thread():
    alive = {"value": True}

    def make_thread(**kwargs):
        thread = MagicMock()
        thread.is_alive.side_effect = lambda: alive["value"]
        thread.start.side_effect = lambda: None
        return thread

    with patch("books.import_worker.threading.Thread", side_effect=make_thread):
        assert schedule_import_processing() is True
        assert schedule_import_processing() is False
        alive["value"] = False
        assert schedule_import_processing() is True


@pytest.mark.django_db
def test_reclaim_stale_running_jobs(user):
    job = create_isbn_job(user, ["9780143127560"])
    job.status = ImportJobStatus.RUNNING
    job.started_at = timezone.now() - timedelta(minutes=31)
    job.save(update_fields=["status", "started_at"])

    reclaimed = reclaim_stale_running_jobs()
    assert reclaimed == 1
    job.refresh_from_db()
    assert job.status == ImportJobStatus.PENDING
    assert job.started_at is None


@pytest.mark.django_db
@override_settings(IMPORT_JOB_AUTO_PROCESS=False)
def test_import_job_process_view(logged_in_client, web_user):
    job = create_isbn_job(web_user, ["9780143127561"])

    with patch("books.web_views.schedule_import_processing") as mock_schedule:
        response = logged_in_client.post(
            reverse("web:import-job-process", kwargs={"pk": job.pk}),
        )
        mock_schedule.assert_called_once_with(force=True)

    assert response.status_code == 204
    with _mock_metadata():
        drain_pending_jobs()
    job.refresh_from_db()
    assert job.status == ImportJobStatus.COMPLETED


@pytest.mark.django_db
def test_create_isbn_job_schedules_processing_on_commit(user):
    from django.test import TestCase

    case = TestCase(methodName="run")
    case._pre_setup()
    try:
        with patch("books.import_worker.schedule_import_processing") as mock_schedule:
            with case.captureOnCommitCallbacks(execute=True):
                create_isbn_job(user, ["9780143127562"])
            mock_schedule.assert_called_once()
    finally:
        case._post_teardown()
