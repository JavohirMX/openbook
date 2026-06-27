from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.dom import minidom

from django.http import HttpResponse
from django.utils import timezone

from accounts.models import ApiToken, UserProfile
from books.embed import read_books, want_to_read_books


ATOM_NS = "http://www.w3.org/2005/Atom"
OPDS_NS = "http://opds-spec.org/ns/1.0"
DC_NS = "http://purl.org/dc/terms/"


def _authenticate_opds_request(request):
    key = request.GET.get("key", "").strip()
    if key:
        profile = UserProfile.objects.filter(embed_enabled=True, embed_key=key).first()
        if profile:
            return profile.user

    token_key = request.GET.get("token", "").strip()
    if not token_key:
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.lower().startswith("token "):
            token_key = auth_header[6:].strip()

    if token_key:
        try:
            token = ApiToken.objects.select_related("user").get(key=token_key)
        except ApiToken.DoesNotExist:
            return None
        if token.user.is_active:
            ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
            return token.user
    return None


def _book_entry(book_data: dict, *, feed_url: str, category: str) -> ET.Element:
    entry = ET.Element(f"{{{ATOM_NS}}}entry")

    ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = book_data["title"]

    authors = book_data.get("authors") or []
    if authors:
        author_el = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
        ET.SubElement(author_el, f"{{{ATOM_NS}}}name").text = authors[0]

    book_id = book_data["id"]
    book_url = book_data.get("url") or f"/books/{book_id}/"
    if book_url.startswith("/"):
        book_url = feed_url.rsplit("/opds", 1)[0] + book_url

    ET.SubElement(
        entry,
        f"{{{ATOM_NS}}}id",
    ).text = f"urn:openbook:book:{book_id}"

    link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
    link.set("rel", "alternate")
    link.set("type", "text/html")
    link.set("href", book_url)

    updated = timezone.now().isoformat()
    ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = updated

    cat = ET.SubElement(entry, f"{{{ATOM_NS}}}category")
    cat.set("term", category)
    cat.set("label", category.replace("-", " ").title())

    isbn = book_data.get("isbn_13") or book_data.get("isbn_10")
    if isbn:
        ET.SubElement(entry, f"{{{DC_NS}}}identifier").text = f"urn:isbn:{isbn}"

    summary_bits = []
    if authors:
        summary_bits.append(", ".join(authors))
    if book_data.get("finished_at"):
        summary_bits.append(f"Finished {book_data['finished_at'][:10]}")
    if summary_bits:
        ET.SubElement(entry, f"{{{ATOM_NS}}}summary").text = " · ".join(summary_bits)

    return entry


def _build_feed(*, title: str, feed_id: str, feed_url: str, entries: list[ET.Element]) -> str:
    feed = ET.Element(
        f"{{{ATOM_NS}}}feed",
        {
            "xmlns": ATOM_NS,
            "xmlns:opds": OPDS_NS,
            "xmlns:dcterms": DC_NS,
        },
    )

    ET.SubElement(feed, f"{{{ATOM_NS}}}title").text = title
    ET.SubElement(feed, f"{{{ATOM_NS}}}id").text = feed_id
    ET.SubElement(feed, f"{{{ATOM_NS}}}updated").text = timezone.now().isoformat()

    self_link = ET.SubElement(feed, f"{{{ATOM_NS}}}link")
    self_link.set("rel", "self")
    self_link.set("type", "application/atom+xml;profile=opds-catalog")
    self_link.set("href", feed_url)

    author_el = ET.SubElement(feed, f"{{{ATOM_NS}}}author")
    ET.SubElement(author_el, f"{{{ATOM_NS}}}name").text = "openbook"

    for entry in entries:
        feed.append(entry)

    rough = ET.tostring(feed, encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="  ")


def opds_catalog_response(request) -> HttpResponse:
    user = _authenticate_opds_request(request)
    if user is None:
        return HttpResponse("Unauthorized", status=401)

    feed_url = request.build_absolute_uri(request.path)
    if request.GET:
        feed_url = request.build_absolute_uri()

    want = want_to_read_books(request=request)
    read = read_books(request=request)

    entries: list[ET.Element] = []
    for book_data in want:
        entries.append(_book_entry(book_data, feed_url=feed_url, category="to-read"))
    for book_data in read:
        entries.append(_book_entry(book_data, feed_url=feed_url, category="read"))

    xml = _build_feed(
        title="openbook library",
        feed_id="urn:openbook:opds:catalog",
        feed_url=feed_url,
        entries=entries,
    )
    return HttpResponse(xml, content_type="application/atom+xml;profile=opds-catalog")
