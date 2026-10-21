import io
import zipfile

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from accounts.factories import UserFactory
from books import epub_metadata
from books.epub_metadata import EpubMetadataError, extract_metadata_from_upload

CONTAINER = (
    '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="content.opf"/></rootfiles></container>'
)
OPF = (
    '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>'
    "<dc:title>Small Book</dc:title><dc:creator>Ann Author</dc:creator></metadata></package>"
)


def make_epub(container=CONTAINER, opf=OPF):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", container)
        z.writestr("content.opf", opf)
    return SimpleUploadedFile("b.epub", buf.getvalue())


def test_reads_title_and_author_from_a_normal_epub():
    meta = extract_metadata_from_upload(make_epub())
    assert meta["title"] == "Small Book"
    assert meta["authors"] == ["Ann Author"]


def test_oversized_xml_member_is_refused_with_a_clear_error(monkeypatch):
    monkeypatch.setattr(epub_metadata, "MAX_XML_BYTES", 1024)
    upload = make_epub(opf=OPF + " " * 5000)
    with pytest.raises(EpubMetadataError, match="too large"):
        extract_metadata_from_upload(upload)


def test_oversized_upload_is_refused(monkeypatch):
    monkeypatch.setattr(epub_metadata, "MAX_UPLOAD_BYTES", 100)
    with pytest.raises(EpubMetadataError, match="too large"):
        extract_metadata_from_upload(make_epub())


def test_not_a_zip_and_broken_xml_give_clear_errors():
    with pytest.raises(EpubMetadataError, match="not a valid EPUB"):
        extract_metadata_from_upload(SimpleUploadedFile("x.epub", b"not a zip"))
    with pytest.raises(EpubMetadataError, match="could not be read"):
        extract_metadata_from_upload(make_epub(container="<container><oops>"))
    with pytest.raises(EpubMetadataError, match="could not be read"):
        extract_metadata_from_upload(SimpleUploadedFile("x.opf", b"<package><metadata>"))


@pytest.mark.django_db
class TestEpubLookupView:
    @pytest.fixture
    def logged_in(self, client):
        UserFactory(email="epub@example.com", password="password123")
        client.login(username="epub@example.com", password="password123")
        return client

    def test_valid_epub_prefills_the_form(self, logged_in):
        r = logged_in.post(reverse("web:book-epub-metadata"), {"epub_file": make_epub()})
        assert r.status_code == 200
        assert b"Small Book" in r.content

    def test_oversized_epub_shows_a_message_not_a_server_error(self, logged_in, monkeypatch):
        monkeypatch.setattr(epub_metadata, "MAX_XML_BYTES", 1024)
        r = logged_in.post(
            reverse("web:book-epub-metadata"), {"epub_file": make_epub(opf=OPF + " " * 5000)}
        )
        assert r.status_code == 200
        assert b"too large" in r.content

    def test_requires_login(self, client):
        r = client.post(reverse("web:book-epub-metadata"), {"epub_file": make_epub()})
        assert r.status_code in (302, 401, 403)

    def test_form_swaps_the_result_into_the_lookup_area_not_the_form_fields(self, logged_in):
        html = logged_in.get(reverse("web:book-add")).content.decode()
        epub_form = html[html.index('hx-post="' + reverse("web:book-epub-metadata"))
                         :html.index("EPUB / OPF metadata") + 700]
        assert 'hx-target="#lookup-result"' in epub_form
        assert 'id="lookup-result"' in html
