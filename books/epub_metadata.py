"""Extract Dublin Core metadata from EPUB and OPF files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO

from django.core.files.uploadedfile import UploadedFile


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _parse_opf_xml(content: bytes) -> dict:
    root = ET.fromstring(content)
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
    with zipfile.ZipFile(BytesIO(data)) as archive:
        container_path = "META-INF/container.xml"
        if container_path not in archive.namelist():
            return None
        container = ET.fromstring(archive.read(container_path))
        opf_path = None
        for element in container.iter():
            if _local(element.tag) == "rootfile":
                opf_path = element.attrib.get("full-path")
                break
        if not opf_path or opf_path not in archive.namelist():
            return None
        return archive.read(opf_path)


def extract_metadata_from_upload(upload: UploadedFile) -> dict:
    name = (upload.name or "").lower()
    data = upload.read()
    upload.seek(0)

    if name.endswith(".opf"):
        return _parse_opf_xml(data)

    if name.endswith(".epub"):
        opf_bytes = _read_epub_opf(data)
        if opf_bytes:
            return _parse_opf_xml(opf_bytes)

    return {}
