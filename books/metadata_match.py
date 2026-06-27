"""Title/author metadata matching, scoring, and book-level lookup orchestration."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from django.conf import settings

from books.import_export import _find_duplicate
from books.metadata import MetadataService
from books.metadata_merge import merge_metadata_best_per_field
from books.metadata_openlibrary import hydrate_candidate
from books.models import Book, MetadataMatchProposal, MetadataMatchProposalStatus


@dataclass
class LookupResult:
    metadata: dict = field(default_factory=dict)
    score: float = 0.0
    alternates: list[dict] = field(default_factory=list)
    source_summary: str = ""
    auto_apply: bool = False
    needs_review: bool = False


def auto_apply_threshold() -> float:
    return float(getattr(settings, "METADATA_AUTO_APPLY_THRESHOLD", 0.82))


def review_gap_threshold() -> float:
    return float(getattr(settings, "METADATA_REVIEW_GAP_THRESHOLD", 0.08))


def _normalize_title(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _author_last_name(author: str) -> str:
    parts = (author or "").strip().split()
    return parts[-1].lower() if parts else ""


def _primary_author(book: Book) -> str:
    author = book.authors.order_by("book_authors__position").first()
    return author.name if author else ""


def _book_context(book: Book) -> dict:
    authors = list(book.authors.order_by("book_authors__position").values_list("name", flat=True))
    return {
        "title": book.title,
        "authors": authors,
        "isbn_13": book.isbn_13,
        "isbn_10": book.isbn_10,
    }


def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def score_candidate(book: Book, candidate: dict) -> float:
    if not candidate.get("title"):
        return 0.0

    title_score = _title_similarity(book.title, candidate.get("title", ""))
    if title_score < 0.55:
        return title_score * 0.5

    primary = _primary_author(book)
    candidate_authors = candidate.get("authors") or []
    author_match = False
    if primary and candidate_authors:
        book_last = _author_last_name(primary)
        author_match = any(_author_last_name(a) == book_last for a in candidate_authors)
    elif not primary and candidate_authors:
        author_match = True

    if not author_match:
        return title_score * 0.6

    score = title_score * 0.7 + 0.3
    if book.isbn_13 and candidate.get("isbn_13") == book.isbn_13:
        score += 0.15
    if book.isbn_10 and candidate.get("isbn_10") == book.isbn_10:
        score += 0.1
    return min(score, 1.0)


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        key = c.get("isbn_13") or c.get("wikidata_id") or c.get("google_books_id") or c.get("hardcover_edition_id")
        if not key:
            key = f"{_normalize_title(c.get('title', ''))}|{'|'.join(c.get('authors') or [])}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


def _search_all_sources(service: MetadataService, query: str, *, import_context: bool) -> list[dict]:
    return service.search_books(query, limit=8, import_context=import_context)


def _score_and_rank(book: Book, candidates: list[dict]) -> list[tuple[dict, float]]:
    scored = [(c, score_candidate(book, c)) for c in candidates if c.get("title")]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _should_auto_apply(scored: list[tuple[dict, float]]) -> bool:
    if not scored:
        return False
    top_score = scored[0][1]
    if top_score < auto_apply_threshold():
        return False
    if len(scored) > 1:
        gap = top_score - scored[1][1]
        if gap < review_gap_threshold():
            return False
    return True


def lookup_for_book(book: Book, *, import_context: bool = False) -> LookupResult:
    service = MetadataService()
    context = _book_context(book)
    candidates: list[dict] = []

    isbn = book.isbn_13 or book.isbn_10
    if isbn:
        isbn_meta = service.lookup_isbn(isbn, import_context=import_context)
        if isbn_meta:
            hydrated = hydrate_candidate(
                isbn_meta,
                service.session,
                get_fn=service._get_openlibrary_json,
                import_context=import_context,
            )
            candidates.append(hydrated)

    query_parts = [book.title]
    primary = _primary_author(book)
    if primary:
        query_parts.append(primary)
    query = " ".join(query_parts).strip()

    if query and (not candidates or not candidates[0].get("cover_url") or not candidates[0].get("genres")):
        search_hits = _search_all_sources(service, query, import_context=import_context)
        for hit in search_hits[:5]:
            hydrated = hydrate_candidate(
                hit,
                service.session,
                get_fn=service._get_openlibrary_json,
                import_context=import_context,
            )
            candidates.append(hydrated)

    if not candidates:
        return LookupResult()

    scored = _score_and_rank(book, candidates)
    if not scored:
        return LookupResult()

    top_meta, top_score = scored[0]
    alternates = [c for c, _ in scored[1:4]]
    auto_apply = _should_auto_apply(scored) if not isbn else top_score >= auto_apply_threshold()
    needs_review = bool(top_meta) and not auto_apply

    return LookupResult(
        metadata=top_meta,
        score=top_score,
        alternates=alternates,
        source_summary=top_meta.get("source_summary", ""),
        auto_apply=auto_apply,
        needs_review=needs_review,
    )


def _isbn_available_for_book(book: Book, metadata: dict) -> bool:
    isbn_13 = metadata.get("isbn_13")
    isbn_10 = metadata.get("isbn_10")
    if not isbn_13 and not isbn_10:
        return True
    dup = _find_duplicate(
        isbn_13=isbn_13 if not book.isbn_13 else None,
        isbn_10=isbn_10 if not book.isbn_10 else None,
    )
    if dup and dup.pk != book.pk:
        return False
    return True


def apply_lookup_result(book: Book, result: LookupResult, *, mode: str = "fill"):
    from books.library_maintenance import EnrichResult, enrich_book_from_metadata

    if not result.metadata:
        return EnrichResult()
    metadata = dict(result.metadata)
    if not _isbn_available_for_book(book, metadata):
        metadata.pop("isbn_13", None)
        metadata.pop("isbn_10", None)
    return enrich_book_from_metadata(book, metadata, mode=mode)


def lookup_metadata_for_import(
    parsed: dict,
    *,
    service: MetadataService | None = None,
    import_context: bool = False,
) -> dict:
    """Resolve metadata for CSV/ISBN import rows (no review queue)."""
    svc = service or MetadataService()
    isbn = parsed.get("isbn_13") or parsed.get("isbn_10")
    if isbn:
        meta = svc.lookup_isbn(isbn, import_context=import_context)
        if meta.get("title"):
            return meta

    title = parsed.get("title") or ""
    author = parsed.get("author") or ""
    if not author and parsed.get("authors"):
        authors = parsed["authors"]
        author = authors[0] if isinstance(authors, list) else str(authors)

    if not title:
        return {}

    query = f"{title} {author}".strip()
    results = svc.search_books(query, limit=5, import_context=import_context)
    if not results:
        return {}

    book_context = {"title": title, "authors": [author] if author else []}
    scored = [(c, score_candidate_data(book_context, c)) for c in results]
    scored.sort(key=lambda x: x[1], reverse=True)
    best, best_score = scored[0]
    if best_score < 0.55:
        return {}

    hydrated = hydrate_candidate(
        best,
        svc.session,
        get_fn=svc._get_openlibrary_json,
        import_context=import_context,
    )
    return merge_metadata_best_per_field(hydrated, book_context=book_context)


def score_candidate_data(book_context: dict, candidate: dict) -> float:
    """Score a candidate against import row context (title + author strings)."""

    class _AuthorProxy:
        def __init__(self, name: str):
            self.name = name

    class _BookProxy:
        def __init__(self, ctx: dict):
            self.title = ctx.get("title", "")
            self.isbn_13 = ctx.get("isbn_13")
            self.isbn_10 = ctx.get("isbn_10")
            self._author_names = ctx.get("authors") or []

        @property
        def authors(self):
            class _QS:
                def __init__(self, author_names):
                    self._author_names = author_names

                def order_by(self, *args):
                    return self

                def first(self):
                    if not self._author_names:
                        return None
                    return _AuthorProxy(self._author_names[0])

            return _QS(self._author_names)

    return score_candidate(_BookProxy(book_context), candidate)


def create_or_update_proposal(book: Book, result: LookupResult) -> MetadataMatchProposal | None:
    if not result.needs_review or not result.metadata:
        return None

    MetadataMatchProposal.objects.filter(
        book=book,
        status=MetadataMatchProposalStatus.PENDING,
    ).delete()

    return MetadataMatchProposal.objects.create(
        book=book,
        candidate=result.metadata,
        score=result.score,
        alternates=result.alternates,
        status=MetadataMatchProposalStatus.PENDING,
        source_summary=result.source_summary or result.metadata.get("source_summary", ""),
    )
