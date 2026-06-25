from django.utils import timezone

from books.models import ReadingProgress, ReadingStatus


def update_reading_log(reading_log, data):
    """Apply reading status lifecycle rules and optional progress updates."""
    old_status = reading_log.status
    today = timezone.localdate()

    if reading_log.total_pages is None and reading_log.book.pages:
        reading_log.total_pages = reading_log.book.pages

    if "status" in data:
        reading_log.status = data["status"]

    new_status = reading_log.status

    if old_status != new_status:
        if (
            old_status == ReadingStatus.NOT_STARTED
            and new_status == ReadingStatus.READING
            and not reading_log.started_at
        ):
            reading_log.started_at = today
        elif old_status == ReadingStatus.READING and new_status == ReadingStatus.FINISHED:
            reading_log.finished_at = today
            reading_log.progress_percent = 100
            if reading_log.total_pages is not None:
                reading_log.current_page = reading_log.total_pages
            reading_log.read_count += 1
        elif old_status == ReadingStatus.FINISHED and new_status == ReadingStatus.READING:
            reading_log.finished_at = None
            reading_log.started_at = today

    progress_fields = ("current_page", "progress_percent", "pages_read")
    for field in progress_fields:
        if field in data:
            setattr(reading_log, field, data[field])

    if "total_pages" in data:
        reading_log.total_pages = data["total_pages"]

    reading_log.save()

    should_log_progress = any(field in data for field in progress_fields)
    if old_status != new_status and new_status == ReadingStatus.FINISHED:
        should_log_progress = True

    if should_log_progress:
        ReadingProgress.objects.create(
            reading_log=reading_log,
            book=reading_log.book,
            logged_on=today,
            current_page=reading_log.current_page,
            progress_percent=reading_log.progress_percent,
            pages_read=data.get("pages_read"),
            note=data.get("note"),
        )

    return reading_log
