from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone as dt_timezone

from books.models import ReadingLog, ReadingProgress, ReadingStatus

_AWARE_DATETIME_MIN = datetime.min.replace(tzinfo=dt_timezone.utc)


@dataclass
class TimelineEntry:
    kind: str
    logged_on: date
    label: str
    progress_percent: int | None = None
    current_page: int | None = None
    pages_read: int | None = None
    note: str | None = None
    created_at: datetime | None = None
    entry_id: int | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "logged_on": self.logged_on.isoformat(),
            "label": self.label,
            "progress_percent": self.progress_percent,
            "current_page": self.current_page,
            "pages_read": self.pages_read,
            "note": self.note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "id": self.entry_id,
        }


_STATUS_LABELS = dict(ReadingStatus.choices)


def build_reading_timeline(reading_log: ReadingLog | None) -> list[TimelineEntry]:
    if reading_log is None:
        return []

    entries: list[TimelineEntry] = []
    seen_dates: set[tuple[str, date]] = set()

    for progress in reading_log.progress_entries.order_by("logged_on", "created_at"):
        if progress.note and progress.note.startswith("Status:"):
            label = progress.note.replace("Status:", "", 1).strip()
            kind = "status_change"
        else:
            label = "Progress update"
            if progress.progress_percent is not None:
                label = f"Progress: {progress.progress_percent}%"
            kind = "progress"
        entries.append(
            TimelineEntry(
                kind=kind,
                logged_on=progress.logged_on,
                label=label,
                progress_percent=progress.progress_percent,
                current_page=progress.current_page,
                pages_read=progress.pages_read,
                note=progress.note if kind == "progress" else None,
                created_at=progress.created_at,
                entry_id=progress.pk,
            )
        )
        seen_dates.add((kind, progress.logged_on))

    if reading_log.started_at:
        key = ("started", reading_log.started_at)
        if key not in seen_dates:
            entries.append(
                TimelineEntry(
                    kind="started",
                    logged_on=reading_log.started_at,
                    label="Started reading",
                )
            )

    if reading_log.finished_at:
        key = ("finished", reading_log.finished_at)
        if not any(e.kind == "status_change" and e.logged_on == reading_log.finished_at for e in entries):
            entries.append(
                TimelineEntry(
                    kind="finished",
                    logged_on=reading_log.finished_at,
                    label=_STATUS_LABELS.get(ReadingStatus.FINISHED, "Read"),
                )
            )

    entries.sort(
        key=lambda e: (e.logged_on, e.created_at or _AWARE_DATETIME_MIN),
        reverse=True,
    )
    return entries
