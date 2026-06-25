from __future__ import annotations

import logging
import mimetypes

import requests
from django.core.files.base import ContentFile

from books.metadata import _metadata_timeout, metadata_user_agent
from books.models import Book

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_COVER_BYTES = 2 * 1024 * 1024

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": metadata_user_agent()})
    return _session


def cover_served_url(book: Book, request=None) -> str | None:
    if book.cover_image:
        url = book.cover_image.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url
    return book.cover_url


def download_cover(book: Book, *, url: str | None = None, force: bool = False) -> bool:
    if book.cover_image and not force:
        return True

    source_url = (url or book.cover_url or "").strip()
    if not source_url:
        return False

    try:
        response = _get_session().get(
            source_url,
            timeout=_metadata_timeout(),
            stream=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Cover download failed for book %s: %s", book.pk, exc)
        return False

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    ext = ALLOWED_CONTENT_TYPES.get(content_type)
    if not ext:
        logger.warning(
            "Cover download rejected for book %s: unsupported type %s",
            book.pk,
            content_type,
        )
        return False

    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_COVER_BYTES:
        logger.warning("Cover download rejected for book %s: Content-Length too large", book.pk)
        return False

    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_COVER_BYTES:
            logger.warning("Cover download rejected for book %s: body too large", book.pk)
            return False
        chunks.append(chunk)

    content = b"".join(chunks)
    if not content:
        logger.warning("Cover download rejected for book %s: empty body", book.pk)
        return False

    if book.cover_image:
        book.cover_image.delete(save=False)

    filename = f"{book.pk}.{ext}"
    book.cover_image.save(filename, ContentFile(content), save=True)
    return True


def cover_content_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"
