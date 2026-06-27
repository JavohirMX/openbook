from __future__ import annotations

import logging
import mimetypes
import struct

import requests
from django.conf import settings
from django.core.files.base import ContentFile

from books.models import Book

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/pjpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_COVER_BYTES = 2 * 1024 * 1024
OPENLIBRARY_PLACEHOLDER_MAX_BYTES = 1500
OPENLIBRARY_COVERS_BASE = "https://covers.openlibrary.org"
OPENLIBRARY_COVER_SIZES = ("L", "M", "S")

_SESSION_ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"

_session: requests.Session | None = None


def _metadata_user_agent() -> str:
    app_name = getattr(settings, "METADATA_APP_NAME", "openbook")
    version = getattr(settings, "APP_VERSION", "0.1.0")
    contact = getattr(settings, "OPENLIBRARY_CONTACT_EMAIL", "").strip()
    if contact:
        return f"{app_name}/{version} ({contact})"
    site = "https://books.javohirmx.com"
    if settings.ALLOWED_HOSTS:
        host = next((h for h in settings.ALLOWED_HOSTS if "." in h), None)
        if host:
            site = f"https://{host}"
    return f"{app_name}/{version} (+{site})"


def _metadata_timeout() -> tuple[float, float]:
    connect = float(getattr(settings, "METADATA_CONNECT_TIMEOUT", 5))
    read = float(getattr(settings, "METADATA_READ_TIMEOUT", 10))
    return (connect, read)


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": _metadata_user_agent(),
            "Accept": _SESSION_ACCEPT,
        })
    return _session


def is_openlibrary_cover_url(url: str) -> bool:
    return "covers.openlibrary.org" in (url or "")


def with_default_false(url: str) -> str:
    if not is_openlibrary_cover_url(url):
        return url
    if "default=false" in url:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}default=false"


def _image_dimensions(content: bytes) -> tuple[int, int] | None:
    if len(content) >= 10 and content[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", content[6:10])
        return width, height
    if len(content) >= 24 and content[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", content[16:24])
        return width, height
    return None


def is_placeholder_image(content: bytes, *, openlibrary: bool = False) -> bool:
    if not content:
        return True
    dims = _image_dimensions(content)
    if dims == (1, 1):
        return True
    if openlibrary and len(content) < OPENLIBRARY_PLACEHOLDER_MAX_BYTES:
        sniffed = _sniff_image_ext(content)
        if sniffed is None or dims is None:
            return True
    return False


def resolve_openlibrary_cover_urls(
    *,
    cover_id: int | None = None,
    edition_olid: str | None = None,
    isbn_13: str | None = None,
    isbn_10: str | None = None,
) -> list[str]:
    urls: list[str] = []
    if cover_id is not None and cover_id > 0:
        for size in OPENLIBRARY_COVER_SIZES:
            urls.append(f"{OPENLIBRARY_COVERS_BASE}/b/id/{cover_id}-{size}.jpg")
    if edition_olid:
        olid = str(edition_olid).removeprefix("/books/").strip("/")
        if olid:
            for size in OPENLIBRARY_COVER_SIZES:
                urls.append(f"{OPENLIBRARY_COVERS_BASE}/b/olid/{olid}-{size}.jpg")
    for isbn in (isbn_13, isbn_10):
        if isbn:
            for size in OPENLIBRARY_COVER_SIZES:
                urls.append(f"{OPENLIBRARY_COVERS_BASE}/b/isbn/{isbn}-{size}.jpg")
    return urls


def resolve_openlibrary_cover_url(
    *,
    cover_id: int | None = None,
    edition_olid: str | None = None,
    isbn_13: str | None = None,
    isbn_10: str | None = None,
    extra_urls: list[str] | None = None,
) -> str | None:
    candidates: list[str] = []
    if extra_urls:
        candidates.extend(extra_urls)
    candidates.extend(
        resolve_openlibrary_cover_urls(
            cover_id=cover_id,
            edition_olid=edition_olid,
            isbn_13=isbn_13,
            isbn_10=isbn_10,
        )
    )
    return fetch_valid_cover_url(candidates)


def fetch_valid_cover_url(candidates: list[str]) -> str | None:
    session = _get_session()
    seen: set[str] = set()
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        probe_url = with_default_false(url)
        try:
            response = session.get(
                probe_url,
                timeout=_metadata_timeout(),
                stream=True,
            )
        except requests.RequestException:
            continue
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            continue

        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_COVER_BYTES:
            continue

        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            size += len(chunk)
            if size > MAX_COVER_BYTES:
                chunks = []
                break
            chunks.append(chunk)

        content = b"".join(chunks)
        if not content or is_placeholder_image(content, openlibrary=True):
            continue
        return url
    return None


def _sniff_image_ext(content: bytes) -> str | None:
    if len(content) >= 3 and content[:3] == b"\xff\xd8\xff":
        return "jpg"
    if len(content) >= 8 and content[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    if len(content) >= 6 and content[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def _extension_for_response(content_type: str, content: bytes) -> str | None:
    normalized = content_type.split(";")[0].strip().lower()
    sniffed = _sniff_image_ext(content)
    declared = ALLOWED_CONTENT_TYPES.get(normalized)
    if sniffed and declared and sniffed != declared:
        return sniffed
    if declared:
        return declared
    if not sniffed:
        return None
    if normalized.startswith("text/"):
        return None
    if normalized in ("", "application/octet-stream", "binary/octet-stream", "application/download"):
        return sniffed
    return sniffed


def _fetch_cover_bytes(url: str) -> tuple[bytes, str] | None:
    fetch_url = with_default_false(url) if is_openlibrary_cover_url(url) else url
    try:
        response = _get_session().get(
            fetch_url,
            timeout=_metadata_timeout(),
            stream=True,
        )
    except requests.RequestException as exc:
        logger.warning("Cover download failed for %s: %s", url, exc)
        return None

    if response.status_code == 404:
        return None
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Cover download failed for %s: %s", url, exc)
        return None

    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    content_length = response.headers.get("Content-Length")
    if content_length and int(content_length) > MAX_COVER_BYTES:
        logger.warning("Cover download rejected for %s: Content-Length too large", url)
        return None

    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_COVER_BYTES:
            logger.warning("Cover download rejected for %s: body too large", url)
            return None
        chunks.append(chunk)

    content = b"".join(chunks)
    if not content or is_placeholder_image(
        content,
        openlibrary=is_openlibrary_cover_url(url),
    ):
        return None

    ext = _extension_for_response(content_type, content)
    if not ext:
        logger.warning(
            "Cover download rejected for %s: unsupported type %s",
            url,
            content_type or "(missing)",
        )
        return None
    return content, ext


def _save_cover_bytes(book: Book, content: bytes, ext: str) -> bool:
    if book.cover_image:
        book.cover_image.delete(save=False)
    filename = f"{book.pk}.{ext}"
    book.cover_image.save(filename, ContentFile(content), save=True)
    return True


def _try_save_cover_from_url(book: Book, url: str) -> bool:
    fetched = _fetch_cover_bytes(url)
    if not fetched:
        return False
    content, ext = fetched
    return _save_cover_bytes(book, content, ext)


def _read_cover_image_bytes(book: Book) -> bytes:
    if not book.cover_image:
        return b""
    try:
        with book.cover_image.open("rb") as cover_file:
            return cover_file.read()
    except OSError:
        return b""


def stored_cover_is_valid(book: Book) -> bool:
    if not book.cover_image:
        return False
    return not is_placeholder_image(_read_cover_image_bytes(book), openlibrary=True)


def has_valid_cover(book: Book) -> bool:
    if stored_cover_is_valid(book):
        return True
    return bool(book.cover_url)


def cover_display_url_for(book: Book) -> str:
    if book.cover_image:
        if stored_cover_is_valid(book):
            return book.cover_image.url
        return ""
    if book.cover_url:
        url = book.cover_url
        if is_openlibrary_cover_url(url):
            return with_default_false(url)
        return url
    return ""


def clear_invalid_stored_cover(book: Book) -> bool:
    """Remove placeholder cover_image only; no network."""
    if not book.cover_image:
        return False
    try:
        with book.cover_image.open("rb") as cover_file:
            content = cover_file.read()
    except OSError:
        content = b""
    if is_placeholder_image(content, openlibrary=True):
        book.cover_image.delete(save=False)
        book.save(update_fields=["cover_image"])
        return True
    return False


def clear_invalid_cover(book: Book, *, verify_remote: bool = True) -> bool:
    changed_fields: list[str] = []
    if book.cover_image:
        try:
            with book.cover_image.open("rb") as cover_file:
                content = cover_file.read()
        except OSError:
            content = b""
        if is_placeholder_image(content, openlibrary=True):
            book.cover_image.delete(save=False)
            changed_fields.append("cover_image")

    needs_remote_check = verify_remote and not stored_cover_is_valid(book)
    if needs_remote_check and book.cover_url and is_openlibrary_cover_url(book.cover_url):
        candidates = [book.cover_url, *resolve_openlibrary_cover_urls(
            edition_olid=book.openlibrary_edition_key,
            isbn_13=book.isbn_13,
            isbn_10=book.isbn_10,
        )]
        if fetch_valid_cover_url(candidates) is None:
            book.cover_url = None
            changed_fields.append("cover_url")

    if changed_fields:
        book.save(update_fields=changed_fields)
        return True
    return False


def cover_served_url(book: Book, request=None) -> str | None:
    display_url = cover_display_url_for(book)
    if not display_url:
        return None
    if request is not None and display_url.startswith("/"):
        return request.build_absolute_uri(display_url)
    return display_url


def download_cover(book: Book, *, url: str | None = None, force: bool = False) -> bool:
    clear_invalid_cover(book, verify_remote=not stored_cover_is_valid(book))
    if force and book.cover_image:
        book.cover_image.delete(save=False)
        book.save(update_fields=["cover_image"])
    elif stored_cover_is_valid(book):
        return True

    source_url = (url or book.cover_url or "").strip()
    urls_to_try: list[str] = []
    if source_url:
        urls_to_try.append(source_url)

    if is_openlibrary_cover_url(source_url) or not source_url:
        resolved = resolve_openlibrary_cover_url(
            edition_olid=book.openlibrary_edition_key,
            isbn_13=book.isbn_13,
            isbn_10=book.isbn_10,
        )
        if resolved and resolved not in urls_to_try:
            urls_to_try.append(resolved)

    for try_url in urls_to_try:
        if _try_save_cover_from_url(book, try_url):
            if try_url != book.cover_url:
                book.cover_url = try_url
                book.save(update_fields=["cover_url"])
            return True

    if book.isbn_13:
        from books.metadata_archive import lookup_archive_cover

        archive_meta = lookup_archive_cover(book.isbn_13, _get_session(), import_context=True)
        archive_url = (archive_meta or {}).get("cover_url")
        if archive_url and archive_url not in urls_to_try:
            if _try_save_cover_from_url(book, archive_url):
                book.cover_url = archive_url
                book.save(update_fields=["cover_url"])
                return True

    return False


def cover_content_type(path: str) -> str:
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


class CoverUploadError(ValueError):
    """Raised when a user-uploaded cover file fails validation."""


def validate_cover_upload(uploaded_file) -> tuple[bytes, str]:
    """Validate a user-uploaded cover file; return (bytes, extension)."""
    content = uploaded_file.read()
    if not content:
        raise CoverUploadError("Cover image file is empty.")
    if len(content) > MAX_COVER_BYTES:
        raise CoverUploadError("Cover image must be 2 MB or smaller.")

    content_type = getattr(uploaded_file, "content_type", "") or ""
    ext = _extension_for_response(content_type, content)
    if not ext:
        raise CoverUploadError("Cover must be JPEG, PNG, WebP, or GIF.")
    if is_placeholder_image(content, openlibrary=True):
        raise CoverUploadError("Cover image is too small or invalid.")

    return content, ext


def lock_cover_metadata(book: Book) -> None:
    locked = list(book.metadata_locked_fields or [])
    if "cover_url" not in locked:
        locked.append("cover_url")
        book.metadata_locked_fields = locked
        book.save(update_fields=["metadata_locked_fields", "updated_at"])


def save_uploaded_cover(book: Book, uploaded_file) -> bool:
    content, ext = validate_cover_upload(uploaded_file)
    _save_cover_bytes(book, content, ext)
    lock_cover_metadata(book)
    return True


def remove_stored_cover(book: Book) -> bool:
    if not book.cover_image:
        return False
    book.cover_image.delete(save=False)
    book.save(update_fields=["cover_image", "updated_at"])
    return True
