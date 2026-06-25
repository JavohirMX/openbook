from __future__ import annotations

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from books.import_export import import_goodreads_csv, import_isbns, preview_goodreads_csv
from books.library_maintenance import BackfillResult, backfill_metadata
from books.models import ImportJob, ImportJobKind, ImportJobStatus


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
    job = ImportJob.objects.create(
        user=user,
        kind=ImportJobKind.GOODREADS_CSV,
        status=ImportJobStatus.AWAITING_CONFIRMATION,
    )
    job.csv_file.save(uploaded_file.name, uploaded_file, save=True)
    with job.csv_file.open("rb") as handle:
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


def confirm_csv_job(job: ImportJob) -> ImportJob:
    if job.kind != ImportJobKind.GOODREADS_CSV:
        raise ValueError("Not a Goodreads CSV job")
    if job.status != ImportJobStatus.AWAITING_CONFIRMATION:
        raise ValueError("Job is not awaiting confirmation")
    job.status = ImportJobStatus.PENDING
    job.save(update_fields=["status"])
    _schedule_import_processing_on_commit()
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
        "errors": result.errors[:20],
    }


def _make_progress_updater(job_id):
    def update_progress(done: int, total: int):
        ImportJob.objects.filter(pk=job_id).update(
            progress_done=done,
            progress_total=total,
        )

    return update_progress


def run_import_job(job: ImportJob) -> ImportJob:
    progress = _make_progress_updater(job.id)
    try:
        if job.kind == ImportJobKind.ISBNS:
            result = import_isbns(job.isbns, progress_callback=progress)
            job.status = ImportJobStatus.COMPLETED
            job.result = _result_to_dict(result)
        elif job.kind == ImportJobKind.GOODREADS_CSV:
            with job.csv_file.open("rb") as handle:
                result = import_goodreads_csv(handle, progress_callback=progress)
            job.status = ImportJobStatus.COMPLETED
            job.result = _result_to_dict(result)
        elif job.kind == ImportJobKind.METADATA_BACKFILL:
            result = backfill_metadata(job.book_ids, progress_callback=progress)
            job.status = ImportJobStatus.COMPLETED
            job.result = _backfill_result_to_dict(result)
        else:
            raise ValueError(f"Unknown job kind: {job.kind}")

        job.error_message = ""
    except Exception as exc:
        job.status = ImportJobStatus.FAILED
        job.error_message = str(exc)
        if "result" in locals():
            if job.kind == ImportJobKind.METADATA_BACKFILL:
                job.result = _backfill_result_to_dict(result)
            else:
                job.result = _result_to_dict(result)
    finally:
        job.finished_at = timezone.now()
        job.save(
            update_fields=[
                "status",
                "result",
                "error_message",
                "progress_done",
                "progress_total",
                "finished_at",
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
