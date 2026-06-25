from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.files.base import ContentFile
from django.urls import reverse

from accounts.factories import UserFactory
from books.covers import cover_served_url, download_cover
from books.factories import BookFactory
from books.library_maintenance import enrich_book_from_metadata
from books.serializers import BookSerializer


def _mock_image_response(content: bytes = b"fake-jpeg", content_type: str = "image/jpeg"):
    response = MagicMock()
    response.headers = {"Content-Type": content_type}
    response.iter_content.return_value = [content]
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.django_db
def test_download_cover_saves_file(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response()
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image
    assert book.cover_image.name.startswith(f"covers/{book.pk}.")
    assert book.cover_display_url == book.cover_image.url


@pytest.mark.django_db
def test_download_cover_skips_when_image_exists(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(b"existing"), save=True)

    with patch("books.covers._get_session") as mock_session:
        assert download_cover(book) is True
        mock_session.return_value.get.assert_not_called()


@pytest.mark.django_db
def test_download_cover_rejects_non_image(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content_type="text/html"
        )
        assert download_cover(book) is False

    book.refresh_from_db()
    assert not book.cover_image


@pytest.mark.django_db
def test_download_cover_rejects_oversized_body(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    huge = b"x" * (2 * 1024 * 1024 + 1)

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(content=huge)
        assert download_cover(book) is False


@pytest.mark.django_db
def test_download_cover_handles_request_failure(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("network down")
        assert download_cover(book) is False


@pytest.mark.django_db
def test_enrich_book_from_metadata_downloads_cover(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url=None, isbn_13="9780143127550")

    with patch("books.library_maintenance.download_cover") as mock_download:
        mock_download.return_value = True
        result = enrich_book_from_metadata(
            book,
            {"cover_url": "https://example.com/cover.jpg"},
        )

    assert "cover_url" in result.updated_fields
    mock_download.assert_called_once_with(book, force=True)


@pytest.mark.django_db
def test_serializer_returns_local_cover_url(settings, tmp_path, rf):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/source.jpg")
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(b"img"), save=True)

    request = rf.get("/")
    data = BookSerializer(book, context={"request": request}).data

    assert data["cover_url"].endswith(book.cover_image.url)
    assert "example.com" not in data["cover_url"]


@pytest.mark.django_db
def test_cover_served_url_prefers_local_file(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/source.jpg")
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(b"img"), save=True)

    assert cover_served_url(book) == book.cover_image.url
    assert cover_served_url(book, None) == book.cover_image.url


@pytest.mark.django_db
def test_serve_cover_view_returns_file(settings, tmp_path, client):
    UserFactory()
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory()
    covers_dir = tmp_path / "covers"
    covers_dir.mkdir()
    filename = f"{book.pk}.jpg"
    (covers_dir / filename).write_bytes(b"jpeg-bytes")

    response = client.get(reverse("serve-cover", kwargs={"path": filename}))
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"jpeg-bytes"
    assert response["Cache-Control"] == "public, max-age=31536000, immutable"


@pytest.mark.django_db
def test_serve_cover_view_blocks_path_traversal(settings, tmp_path, client):
    UserFactory()
    settings.MEDIA_ROOT = tmp_path
    secret_dir = tmp_path / "import_jobs"
    secret_dir.mkdir()
    (secret_dir / "secret.csv").write_text("private", encoding="utf-8")

    response = client.get(reverse("serve-cover", kwargs={"path": "../import_jobs/secret.csv"}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_download_covers_command(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")

    from django.core.management import call_command

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response()
        call_command("download_covers")

    book.refresh_from_db()
    assert book.cover_image
