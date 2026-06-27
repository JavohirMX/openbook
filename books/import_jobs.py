from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from books.import_export import (
    detect_csv_import_kind,
    import_goodreads_csv,
    import_isbns,
    import_storygraph_csv,
    preview_goodreads_csv,
    preview_storygraph_csv,
)
from books.library_maintenance import BackfillResult, EnrichResult, backfill_metadata, refresh_book_metadata
from books.models import Book, ImportJob, ImportJobKind, ImportJobStatus

CANCELLABLE_KINDS = {
    ImportJobKind.METADATA_BACKFILL,
    ImportJobKind.METADATA_REFRESH,
    ImportJobKind.GOODREADS_CSV,
    ImportJobKind.STORYGRAPH_CSV,
}

ShouldStop = Callable[[], bool] | None


def _schedule_import_processing_on_commit() -> None:
    from books.import_worker import schedule_import_processing

    transaction.on_commit(schedule_import_processing)


def _is_postgresql() -> bool:
    return "postgresql" in settings.DATABASES["default"]["ENGINE"]


def create_isbn_job(user, isbns: list[str]) -> ImportJob:
    cleaned = [line.strip() for line in isbns if line.strip()]
    job = ImportJob.objects.create(
        user=user,
        kind=ImportJobKind.ISBNS,
        status=ImportJobStatus.PENDING,
        isbns=cleaned,
        progress_total=len(cleaned),
    )
    _schedule_import_processing_on_commit()
    return job


def create_csv_preview_job(user, uploaded_file) -> ImportJob:
    kind = detect_csv_import_kind(uploaded_file)
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    job = ImportJob.objects.create(
        user=user,
        kind=kind,
        status=ImportJobStatus.AWAITING_CONFIRMATION,
    )
    job.csv_file.save(uploaded_file.name, uploaded_file, save=True)
    with job.csv_file.open("rb") as handle:
        if kind == ImportJobKind.STORYGRAPH_CSV:
            preview = preview_storygraph_csv(handle)
        else:
            preview = preview_goodreads_csv(handle)
    job.preview = preview
    job.progress_total = len(preview)
    job.save(update_fields=["preview", "progress_total"])
    return job


def create_metadata_backfill_job(user, book_ids: list[str]) -> ImportJob:
    cleaned = [str(book_id) for book_id in book_ids if book_id]
    job = ImportJob.objects.create(
        user=user,
        kind=ImportJobKind.METADATA_BACKFILL,
        status=ImportJobStatus.PENDING,
        book_ids=cleaned,
        progress_total=len(cleaned),
    )
    _schedule_import_processing_on_commit()
    return job


def create_metadata_refresh_job(user, book_id: str) -> ImportJob:
    cleaned = str(book_id)
    job = ImportJob.objects.create(
        user=user,
        kind=ImportJobKind.METADATA_REFRESH,
        status=ImportJobStatus.PENDING,
        book_ids=[cleaned],
        progress_total=1,
    )
    _schedule_import_processing_on_commit()
    return job


def active_metadata_refresh_job(user, book_id: str) -> ImportJob | None:
    book_id = str(book_id)
    for job in ImportJob.objects.filter(
        user=user,
        kind=ImportJobKind.METADATA_REFRESH,
        status__in=(ImportJobStatus.PENDING, ImportJobStatus.RUNNING),
    ).order_by("-created_at")[:20]:
        if book_id in (job.book_ids or []):
            return job
    return None


def confirm_csv_job(job: ImportJob) -> ImportJob:
    if job.kind not in (ImportJobKind.GOODREADS_CSV, ImportJobKind.STORYGRAPH_CSV):
        raise ValueError("Not a CSV import job")
    if job.status != ImportJobStatus.AWAITING_CONFIRMATION:
        raise ValueError("Job is not awaiting confirmation")
    job.status = ImportJobStatus.PENDING
    job.save(update_fields=["status"])
    _schedule_import_processing_on_commit()
    return job


def request_cancel_import_job(job: ImportJob) -> ImportJob:
    if job.kind not in CANCELLABLE_KINDS:
        raise ValueError("This job kind cannot be cancelled")
    if job.status not in (ImportJobStatus.PENDING, ImportJobStatus.RUNNING):
        raise ValueError("Job cannot be cancelled in its current state")

    if job.status == ImportJobStatus.PENDING:
        job.status = ImportJobStatus.CANCELLED
        job.cancel_requested = False
        job.cancel_requested_at = None
        job.finished_at = timezone.now()
        job.save(
            update_fields=["status", "cancel_requested", "cancel_requested_at", "finished_at"]
        )
    else:
        job.cancel_requested = True
        job.cancel_requested_at = timezone.now()
        job.save(update_fields=["cancel_requested", "cancel_requested_at"])
    return job


def claim_next_job() -> ImportJob | None:
    with transaction.atomic():
        qs = ImportJob.objects.filter(status=ImportJobStatus.PENDING).order_by("created_at")
        if _is_postgresql():
            job = qs.select_for_update(skip_locked=True).first()
        else:
            job = qs.select_for_update().first()
        if not job:
            return None
        job.status = ImportJobStatus.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
        return job


def _result_to_dict(result) -> dict:
    return {
        "added": result.added,
        "skipped": result.skipped,
        "failed": result.failed,
        "errors": result.errors[:20],
    }


def _backfill_result_to_dict(result: BackfillResult) -> dict:
    return {
        "updated": result.updated,
        "skipped": result.skipped,
        "failed": result.failed,
        "pending_review": result.pending_review,
        "errors": result.errors[:20],
    }


def _refresh_result_to_dict(result: EnrichResult) -> dict:
    return {"updated_fields": result.updated_fields}


def _make_progress_updater(job_id):
    def update_progress(done: int, total: int):
        ImportJob.objects.filter(pk=job_id).update(
            progress_done=done,
            progress_total=total,
        )

    return update_progress


def _make_should_stop(job_id) -> ShouldStop:
    def should_stop() -> bool:
        return ImportJob.objects.filter(pk=job_id, cancel_requested=True).exists()

    return should_stop


def run_import_job(job: ImportJob) -> ImportJob:
    progress = _make_progress_updater(job.id)
    should_stop = _make_should_stop(job.id)
    cancelled = False
    result = None
    try:
        if job.kind == ImportJobKind.ISBNS:
            result = import_isbns(job.isbns, progress_callback=progress)
            job.status = ImportJobStatus.COMPLETED
            job.result = _result_to_dict(result)
        elif job.kind == ImportJobKind.GOODREADS_CSV:
            with job.csv_file.open("rb") as handle:
                result = import_goodreads_csv(
                    handle,
                    progress_callback=progress,
                    should_stop=should_stop,
                )
            cancelled = should_stop()
            job.result = _result_to_dict(result)
            job.status = ImportJobStatus.CANCELLED if cancelled else ImportJobStatus.COMPLETED
        elif job.kind == ImportJobKind.STORYGRAPH_CSV:
            with job.csv_file.open("rb") as handle:
                result = import_storygraph_csv(
                    handle,
                    progress_callback=progress,
                    should_stop=should_stop,
                )
            cancelled = should_stop()
            job.result = _result_to_dict(result)
            job.status = ImportJobStatus.CANCELLED if cancelled else ImportJobStatus.COMPLETED
        elif job.kind == ImportJobKind.METADATA_BACKFILL:
            result = backfill_metadata(
                job.book_ids,
                progress_callback=progress,
                should_stop=should_stop,
            )
            cancelled = should_stop()
            job.result = _backfill_result_to_dict(result)
            job.status = ImportJobStatus.CANCELLED if cancelled else ImportJobStatus.COMPLETED
        elif job.kind == ImportJobKind.METADATA_REFRESH:
            book_id = job.book_ids[0] if job.book_ids else None
            if not book_id:
                raise ValueError("No book_id on metadata refresh job")
            book = Book.objects.get(pk=book_id)
            result = refresh_book_metadata(book)
            progress(1, 1)
            cancelled = should_stop()
            job.result = _refresh_result_to_dict(result)
            job.status = ImportJobStatus.CANCELLED if cancelled else ImportJobStatus.COMPLETED
        else:
            raise ValueError(f"Unknown job kind: {job.kind}")

        job.error_message = ""
        if job.status == ImportJobStatus.COMPLETED:
            from books.webhooks import emit_import_completed

            emit_import_completed(job)
    except Exception as exc:
        job.status = ImportJobStatus.FAILED
        job.error_message = str(exc)
        if result is not None:
            if job.kind == ImportJobKind.METADATA_BACKFILL:
                job.result = _backfill_result_to_dict(result)
            elif job.kind == ImportJobKind.METADATA_REFRESH:
                job.result = _refresh_result_to_dict(result)
            else:
                job.result = _result_to_dict(result)
    finally:
        job.cancel_requested = False
        job.cancel_requested_at = None
        job.finished_at = timezone.now()
        latest = ImportJob.objects.filter(pk=job.id).values("progress_done", "progress_total").first()
        if latest:
            job.progress_done = latest["progress_done"]
            job.progress_total = latest["progress_total"]
        job.save(
            update_fields=[
                "status",
                "result",
                "error_message",
                "progress_done",
                "progress_total",
                "finished_at",
                "cancel_requested",
                "cancel_requested_at",
            ]
        )
    job.refresh_from_db()
    return job


def serialize_job(job: ImportJob, *, request=None) -> dict:
    data = {
        "id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "progress_done": job.progress_done,
        "progress_total": job.progress_total,
        "result": job.result or {},
        "error_message": job.error_message,
        "cancel_requested": job.cancel_requested,
        "preview": job.preview if job.status == ImportJobStatus.AWAITING_CONFIRMATION else [],
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
    if request is not None:
        from django.urls import reverse

        data["status_url"] = request.build_absolute_uri(
            reverse("api-import-job-detail", kwargs={"pk": job.id})
        )
    return data
