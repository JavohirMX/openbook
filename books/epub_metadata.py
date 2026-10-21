"""Extract Dublin Core metadata from EPUB and OPF files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

# A metadata lookup only needs two small XML files, so cap what we are willing to read.
# Real EPUBs are usually under 30 MB; the XML members are a few KB.
# Defaults can be changed with EPUB_MAX_UPLOAD_MB and EPUB_MAX_XML_MB in settings/env.
MAX_UPLOAD_BYTES = int(getattr(settings, "EPUB_MAX_UPLOAD_MB", 100) * 1024 * 1024)
MAX_XML_BYTES = int(getattr(settings, "EPUB_MAX_XML_MB", 2) * 1024 * 1024)


class EpubMetadataError(ValueError):
    """The file is too large or malformed to read metadata from. The message is safe to show."""


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    """Read one zip member, refusing to inflate more than MAX_XML_BYTES.

    The declared size is checked before anything is inflated, and the read is bounded as a
    second guard (zipfile itself also stops at the declared size).
    """
    info = archive.getinfo(name)
    if info.file_size > MAX_XML_BYTES:
        raise EpubMetadataError("That file's metadata is too large to read.")
    with archive.open(info) as handle:
        data = handle.read(MAX_XML_BYTES + 1)
    if len(data) > MAX_XML_BYTES:
        raise EpubMetadataError("That file's metadata is too large to read.")
    return data


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _parse_opf_xml(content: bytes) -> dict:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise EpubMetadataError("That file's metadata could not be read.") from exc
    metadata: dict = {"authors": [], "genres": []}
    for child in root.iter():
        tag = _local(child.tag)
        text = _text(child)
        if not text:
            continue
        if tag == "title" and "title" not in metadata:
            metadata["title"] = text
        elif tag in ("creator", "author") and text not in metadata["authors"]:
            metadata["authors"].append(text)
        elif tag == "description" and "description" not in metadata:
            metadata["description"] = text
        elif tag == "publisher" and "publisher" not in metadata:
            metadata["publisher"] = text
        elif tag == "date" and "published_year" not in metadata:
            match = re.search(r"(\d{4})", text)
            if match:
                metadata["published_year"] = int(match.group(1))
        elif tag in ("identifier",):
            cleaned = re.sub(r"[^0-9Xx]", "", text)
            if len(cleaned) in (10, 13):
                metadata["isbn_13" if len(cleaned) == 13 else "isbn_10"] = cleaned.upper()
        elif tag in ("subject", "type") and text not in metadata["genres"]:
            metadata["genres"].append(text)
        elif tag == "language" and "language" not in metadata:
            metadata["language"] = text[:10]
    return metadata


def _read_epub_opf(data: bytes) -> bytes | None:
    try:
        archive_cm = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise EpubMetadataError("That file is not a valid EPUB.") from exc
    with archive_cm as archive:
        container_path = "META-INF/container.xml"
        if container_path not in archive.namelist():
            return None
        try:
            container = ET.fromstring(_read_member(archive, container_path))
        except ET.ParseError as exc:
            raise EpubMetadataError("That file's metadata could not be read.") from exc
        opf_path = None
        for element in container.iter():
            if _local(element.tag) == "rootfile":
                opf_path = element.attrib.get("full-path")
                break
        if not opf_path or opf_path not in archive.namelist():
            return None
        return _read_member(archive, opf_path)


def extract_metadata_from_upload(upload: UploadedFile) -> dict:
    name = (upload.name or "").lower()
    if (upload.size or 0) > MAX_UPLOAD_BYTES:
        raise EpubMetadataError(f"That file is too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    data = upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise EpubMetadataError(f"That file is too large (limit {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    upload.seek(0)

    if name.endswith(".opf"):
        if len(data) > MAX_XML_BYTES:
            raise EpubMetadataError("That file's metadata is too large to read.")
        return _parse_opf_xml(data)

    if name.endswith(".epub"):
        opf_bytes = _read_epub_opf(data)
        if opf_bytes:
            return _parse_opf_xml(opf_bytes)

    return {}
