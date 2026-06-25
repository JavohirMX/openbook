from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from books.import_jobs import claim_next_job, run_import_job
from books.models import ImportJob, ImportJobStatus

logger = logging.getLogger(__name__)

_drain_lock = threading.Lock()
_drain_thread: threading.Thread | None = None


def process_one_pending_job() -> bool:
    job = claim_next_job()
    if not job:
        return False
    logger.info("Processing import job %s (%s)", job.id, job.kind)
    job = run_import_job(job)
    if job.status == ImportJobStatus.COMPLETED:
        result = job.result or {}
        logger.info(
            "Import job %s completed: added=%s skipped=%s failed=%s",
            job.id,
            result.get("added", 0),
            result.get("skipped", 0),
            result.get("failed", 0),
        )
    else:
        logger.error("Import job %s failed: %s", job.id, job.error_message)
    return True


def reclaim_stale_running_jobs() -> int:
    stale_minutes = int(getattr(settings, "IMPORT_JOB_STALE_MINUTES", 30))
    cutoff = timezone.now() - timedelta(minutes=stale_minutes)
    updated = ImportJob.objects.filter(
        status=ImportJobStatus.RUNNING,
        started_at__lt=cutoff,
    ).update(
        status=ImportJobStatus.PENDING,
        started_at=None,
    )
    if updated:
        logger.warning("Reclaimed %s stale running import job(s)", updated)
    return updated


def drain_pending_jobs() -> None:
    close_old_connections()
    try:
        reclaim_stale_running_jobs()
        while process_one_pending_job():
            pass
    finally:
        close_old_connections()
        with _drain_lock:
            global _drain_thread
            _drain_thread = None


def _run_drain_thread() -> None:
    try:
        drain_pending_jobs()
    except Exception:
        logger.exception("Import job drain failed")
        with _drain_lock:
            global _drain_thread
            _drain_thread = None


def schedule_import_processing(*, force: bool = False) -> bool:
    if not force and not getattr(settings, "IMPORT_JOB_AUTO_PROCESS", True):
        return False

    global _drain_thread
    with _drain_lock:
        if _drain_thread is not None and _drain_thread.is_alive():
            return False
        _drain_thread = threading.Thread(
            target=_run_drain_thread,
            name="openbook-import",
            daemon=True,
        )
        _drain_thread.start()
    return True
