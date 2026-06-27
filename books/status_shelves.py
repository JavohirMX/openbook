from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Count
from django.http import Http404

from books.models import ReadingLog, ReadingStatus

STATUS_SHELF_DEFINITIONS: tuple[dict[str, str], ...] = (
    {
        "slug": "want-to-read",
        "status": ReadingStatus.NOT_STARTED,
        "name": "Want to Read",
    },
    {
        "slug": "currently-reading",
        "status": ReadingStatus.READING,
        "name": "Currently Reading",
    },
    {
        "slug": "read",
        "status": ReadingStatus.FINISHED,
        "name": "Read",
    },
    {
        "slug": "paused",
        "status": ReadingStatus.PAUSED,
        "name": "Paused",
    },
    {
        "slug": "dnf",
        "status": ReadingStatus.ABANDONED,
        "name": "DNF",
    },
)

_SLUG_TO_DEFINITION = {item["slug"]: item for item in STATUS_SHELF_DEFINITIONS}


@dataclass(frozen=True)
class StatusShelf:
    slug: str
    name: str
    status: str
    book_count: int


def _active_book_count_by_status() -> dict[str, int]:
    return {
        row["status"]: row["count"]
        for row in ReadingLog.objects.filter(book__deleted_at__isnull=True)
        .values("status")
        .annotate(count=Count("id"))
    }


def get_status_shelves() -> list[StatusShelf]:
    counts = _active_book_count_by_status()
    return [
        StatusShelf(
            slug=item["slug"],
            name=item["name"],
            status=item["status"],
            book_count=counts.get(item["status"], 0),
        )
        for item in STATUS_SHELF_DEFINITIONS
    ]


def get_status_shelf(slug: str) -> StatusShelf:
    definition = _SLUG_TO_DEFINITION.get(slug)
    if not definition:
        raise Http404("Status shelf not found")
    counts = _active_book_count_by_status()
    return StatusShelf(
        slug=definition["slug"],
        name=definition["name"],
        status=definition["status"],
        book_count=counts.get(definition["status"], 0),
    )
