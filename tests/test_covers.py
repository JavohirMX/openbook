from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.files.base import ContentFile
from django.urls import reverse

from accounts.factories import UserFactory
from books.covers import (
    clear_invalid_cover,
    clear_invalid_stored_cover,
    cover_display_url_for,
    cover_served_url,
    download_cover,
    fetch_valid_cover_url,
    has_valid_cover,
    is_placeholder_image,
    resolve_openlibrary_cover_urls,
    with_default_false,
)
from books.factories import BookFactory
from books.library_maintenance import enrich_book_from_metadata
from books.serializers import BookSerializer


def _mock_image_response(
    content: bytes = b"fake-jpeg",
    content_type: str = "image/jpeg",
    status_code: int = 200,
):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Content-Type": content_type}
    response.iter_content.return_value = [content]
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


REAL_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2000
OL_PLACEHOLDER_GIF = b"GIF89a" + b"\x01\x00\x01\x00" + b"\x00" * 800


@pytest.mark.django_db
def test_download_cover_saves_file(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(content=REAL_JPEG)
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image
    assert book.cover_image.name.startswith(f"covers/{book.pk}.")
    assert book.cover_display_url == book.cover_image.url


@pytest.mark.django_db
def test_download_cover_skips_when_image_exists(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(REAL_JPEG), save=True)

    with patch("books.covers._get_session") as mock_session:
        assert download_cover(book) is True
        mock_session.return_value.get.assert_not_called()


@pytest.mark.django_db
def test_download_cover_sniffs_when_content_type_missing(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=jpeg,
            content_type="",
        )
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image.name.endswith(".jpg")


@pytest.mark.django_db
def test_download_cover_sniffs_octet_stream(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.png")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=png,
            content_type="application/octet-stream",
        )
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image.name.endswith(".png")


@pytest.mark.django_db
def test_download_cover_rejects_non_image(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=b"<html>not an image</html>",
            content_type="text/html",
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
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(REAL_JPEG), save=True)

    request = rf.get("/")
    data = BookSerializer(book, context={"request": request}).data

    assert data["cover_url"].endswith(book.cover_image.url)
    assert "example.com" not in data["cover_url"]


@pytest.mark.django_db
def test_cover_served_url_prefers_local_file(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/source.jpg")
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(REAL_JPEG), save=True)

    assert cover_served_url(book) == book.cover_image.url
    assert cover_served_url(book, None) == book.cover_image.url


@pytest.mark.django_db
def test_download_cover_sniffs_gif_when_content_type_wrong(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.gif")
    gif = b"GIF89a" + b"\x00" * 100

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=gif,
            content_type="image/jpeg",
        )
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image.name.endswith(".gif")


@pytest.mark.django_db
def test_download_cover_gif_content_type(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.gif")
    gif = b"GIF89a" + b"\x00" * 100

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=gif,
            content_type="image/gif",
        )
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image.name.endswith(".gif")


@pytest.mark.django_db
def test_download_cover_sniffs_png_when_content_type_wrong(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.png")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=png,
            content_type="image/jpeg",
        )
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image.name.endswith(".png")


@pytest.mark.django_db
def test_serve_cover_view_returns_gif_content_type(settings, tmp_path, client):
    UserFactory()
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory()
    covers_dir = tmp_path / "covers"
    covers_dir.mkdir()
    filename = f"{book.pk}.gif"
    (covers_dir / filename).write_bytes(b"GIF89a-bytes")

    response = client.get(reverse("serve-cover", kwargs={"path": filename}))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/gif"


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
        mock_session.return_value.get.return_value = _mock_image_response(content=REAL_JPEG)
        call_command("download_covers")

    book.refresh_from_db()
    assert book.cover_image


@pytest.mark.django_db
def test_clear_invalid_cover_removes_placeholder_image(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(
        cover_url="https://covers.openlibrary.org/b/isbn/9780000000000-L.jpg",
        isbn_13="9780000000000",
    )
    book.cover_image.save(f"{book.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(status_code=404)
        assert clear_invalid_cover(book) is True

    book.refresh_from_db()
    assert not book.cover_image
    assert book.cover_url is None


@pytest.mark.django_db
def test_clear_invalid_stored_cover_removes_placeholder_without_network(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(
        cover_url="https://covers.openlibrary.org/b/isbn/9780000000000-L.jpg",
        isbn_13="9780000000000",
    )
    book.cover_image.save(f"{book.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    with patch("books.covers.fetch_valid_cover_url") as mock_fetch:
        assert clear_invalid_stored_cover(book) is True
        mock_fetch.assert_not_called()

    book.refresh_from_db()
    assert not book.cover_image
    assert book.cover_url is not None


@pytest.mark.django_db
def test_clear_invalid_cover_skips_remote_probe_when_local_cover_valid(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(
        cover_url="https://covers.openlibrary.org/b/isbn/9780143127550-L.jpg",
        isbn_13="9780143127550",
    )
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(REAL_JPEG), save=True)

    with patch("books.covers.fetch_valid_cover_url") as mock_fetch:
        assert clear_invalid_cover(book) is False
        mock_fetch.assert_not_called()


@pytest.mark.django_db
def test_download_covers_clean_invalid_prints_progress(settings, tmp_path, capsys):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    book.cover_image.save(f"{book.pk}.jpg", ContentFile(REAL_JPEG), save=True)

    from django.core.management import call_command

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(content=REAL_JPEG)
        call_command("download_covers", "--clean-invalid", verbosity=1)

    output = capsys.readouterr().out
    assert "Scanning 1 book(s) with cover images" in output
    assert book.title in output


@pytest.mark.django_db
def test_cover_display_url_for_placeholder_file_returns_empty(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/fallback.jpg")
    book.cover_image.save(f"{book.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    assert cover_display_url_for(book) == ""
    assert book.cover_display_url == ""


@pytest.mark.django_db
def test_cover_display_url_for_openlibrary_remote_adds_default_false():
    book = BookFactory(
        cover_url="https://covers.openlibrary.org/b/isbn/9780143127550-L.jpg",
        cover_image="",
    )

    assert book.cover_display_url == (
        "https://covers.openlibrary.org/b/isbn/9780143127550-L.jpg?default=false"
    )


@pytest.mark.django_db
def test_download_cover_retries_after_invalid_stored_image(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    book.cover_image.save(f"{book.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(content=REAL_JPEG)
        assert download_cover(book) is True
        mock_session.return_value.get.assert_called()

    book.refresh_from_db()
    assert book.cover_image
    assert book.cover_image.name.endswith(".jpg")


@pytest.mark.django_db
def test_cover_served_url_returns_none_for_placeholder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/source.jpg")
    book.cover_image.save(f"{book.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    assert cover_served_url(book) is None


@pytest.mark.django_db
def test_has_valid_cover_remote_url_only():
    book = BookFactory(cover_url="https://example.com/cover.jpg", cover_image="")
    assert has_valid_cover(book) is True


@pytest.mark.django_db
def test_download_covers_clean_invalid_command(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(cover_url="https://example.com/cover.jpg")
    book.cover_image.save(f"{book.pk}.gif", ContentFile(OL_PLACEHOLDER_GIF), save=True)

    from django.core.management import call_command

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(content=REAL_JPEG)
        call_command("download_covers", "--clean-invalid")

    book.refresh_from_db()
    assert book.cover_image
    assert book.cover_image.name.endswith(".jpg")


def test_is_placeholder_image_detects_1x1_gif():
    assert is_placeholder_image(OL_PLACEHOLDER_GIF, openlibrary=True) is True


def test_is_placeholder_image_accepts_real_jpeg():
    assert is_placeholder_image(REAL_JPEG, openlibrary=True) is False
    assert is_placeholder_image(REAL_JPEG, openlibrary=False) is False


def test_with_default_false_appends_query_param():
    url = "https://covers.openlibrary.org/b/isbn/9780143127550-L.jpg"
    assert with_default_false(url) == f"{url}?default=false"


def test_resolve_openlibrary_cover_urls_orders_id_olid_isbn():
    urls = resolve_openlibrary_cover_urls(
        cover_id=12345,
        edition_olid="/books/OL123M",
        isbn_13="9780143127550",
    )
    assert urls[0] == "https://covers.openlibrary.org/b/id/12345-L.jpg"
    assert any("olid/OL123M" in url for url in urls)
    assert any("isbn/9780143127550" in url for url in urls)


def test_fetch_valid_cover_url_rejects_404_with_default_false():
    candidates = ["https://covers.openlibrary.org/b/isbn/9780000000000-L.jpg"]

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(status_code=404)
        assert fetch_valid_cover_url(candidates) is None
        called_url = mock_session.return_value.get.call_args[0][0]
        assert "default=false" in called_url


def test_fetch_valid_cover_url_tries_sizes():
    large = "https://covers.openlibrary.org/b/isbn/9780143127550-L.jpg"
    medium = "https://covers.openlibrary.org/b/isbn/9780143127550-M.jpg"

    def fake_get(url, **kwargs):
        if url.startswith(large):
            return _mock_image_response(status_code=404)
        return _mock_image_response(content=REAL_JPEG, content_type="image/jpeg")

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.side_effect = fake_get
        assert fetch_valid_cover_url([large, medium]) == medium


@pytest.mark.django_db
def test_download_cover_rejects_openlibrary_placeholder(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(
        cover_url="https://covers.openlibrary.org/b/isbn/9780000000000-L.jpg",
        isbn_13="9780000000000",
    )

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.return_value = _mock_image_response(
            content=OL_PLACEHOLDER_GIF,
            content_type="image/gif",
        )
        assert download_cover(book) is False

    book.refresh_from_db()
    assert not book.cover_image


@pytest.mark.django_db
def test_download_cover_falls_back_to_next_size(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    book = BookFactory(
        cover_url="https://covers.openlibrary.org/b/isbn/9780143127550-L.jpg",
        isbn_13="9780143127550",
    )
    large = book.cover_url
    medium = "https://covers.openlibrary.org/b/isbn/9780143127550-M.jpg"

    def fake_get(url, **kwargs):
        if "-L.jpg" in url:
            return _mock_image_response(content=OL_PLACEHOLDER_GIF, content_type="image/gif")
        if "-M.jpg" in url:
            return _mock_image_response(content=REAL_JPEG, content_type="image/jpeg")
        return _mock_image_response(status_code=404)

    with patch("books.covers._get_session") as mock_session:
        mock_session.return_value.get.side_effect = fake_get
        assert download_cover(book) is True

    book.refresh_from_db()
    assert book.cover_image
