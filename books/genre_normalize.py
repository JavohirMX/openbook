"""Map raw Open Library / Google Books labels to a curated genre taxonomy."""

from __future__ import annotations

import re
import unicodedata

METADATA_GENRE_LIMIT = 3

CANONICAL_GENRES: frozenset[str] = frozenset({
    "Fiction",
    "Literary Fiction",
    "Mystery",
    "Thriller",
    "Crime",
    "Science Fiction",
    "Fantasy",
    "Romance",
    "Horror",
    "Historical Fiction",
    "Biography",
    "Memoir",
    "History",
    "Science",
    "Technology",
    "Business",
    "Economics",
    "Philosophy",
    "Psychology",
    "Self-Help",
    "Health",
    "Religion",
    "Politics",
    "Travel",
    "Cooking",
    "Poetry",
    "Drama",
    "Young Adult",
    "Children's",
    "Comics and Graphic Novels",
    "Nonfiction",
})

_CANONICAL_BY_LOWER = {name.lower(): name for name in CANONICAL_GENRES}

GENRE_ALIASES: dict[str, str] = {
    "novels": "Fiction",
    "fiction": "Fiction",
    "fiction: literature": "Literary Fiction",
    "literary fiction": "Literary Fiction",
    "fiction, literature": "Literary Fiction",
    "general fiction": "Fiction",
    "fiction, general": "Fiction",
    "fiction, thrillers": "Thriller",
    "fiction, thrillers, general": "Thriller",
    "thrillers": "Thriller",
    "thriller": "Thriller",
    "suspense": "Thriller",
    "fiction, psychological": "Thriller",
    "psychological fiction": "Thriller",
    "fiction, mystery and detective": "Mystery",
    "mystery": "Mystery",
    "detective": "Mystery",
    "crime": "Crime",
    "crime fiction": "Crime",
    "true crime": "Crime",
    "science fiction": "Science Fiction",
    "sci-fi": "Science Fiction",
    "scifi": "Science Fiction",
    "fantasy": "Fantasy",
    "romance": "Romance",
    "horror": "Horror",
    "historical fiction": "Historical Fiction",
    "biography": "Biography",
    "autobiography": "Biography",
    "memoir": "Memoir",
    "history": "History",
    "science": "Science",
    "technology": "Technology",
    "computers": "Technology",
    "business": "Business",
    "economics": "Economics",
    "philosophy": "Philosophy",
    "psychology": "Psychology",
    "self-help": "Self-Help",
    "self help": "Self-Help",
    "conduct of life": "Self-Help",
    "conducta de vida": "Self-Help",
    "self-realization": "Self-Help",
    "personal growth": "Self-Help",
    "health": "Health",
    "religion": "Religion",
    "spirituality": "Religion",
    "politics": "Politics",
    "travel": "Travel",
    "cooking": "Cooking",
    "food": "Cooking",
    "poetry": "Poetry",
    "drama": "Drama",
    "young adult": "Young Adult",
    "young adult fiction": "Young Adult",
    "juvenile fiction": "Children's",
    "children's": "Children's",
    "children": "Children's",
    "graphic novels": "Comics and Graphic Novels",
    "comics": "Comics and Graphic Novels",
    "nonfiction": "Nonfiction",
    "non-fiction": "Nonfiction",
}

GENRE_DENY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^nyt:", re.I),
    re.compile(r"new york times bestseller", re.I),
    re.compile(r"long now manual", re.I),
    re.compile(r"bestseller", re.I),
    re.compile(r"^[a-z]{1,2}$", re.I),
    re.compile(r"\(england\),?\s*fiction$", re.I),
    re.compile(r"^[a-z\s]+,\s*fiction$", re.I),
)

_KEYWORD_RULES: tuple[tuple[re.Pattern[str], str, int], ...] = (
    (re.compile(r"thriller", re.I), "Thriller", 80),
    (re.compile(r"mystery|detective", re.I), "Mystery", 75),
    (re.compile(r"\bcrime\b", re.I), "Crime", 70),
    (re.compile(r"psychological", re.I), "Thriller", 65),
    (re.compile(r"science fiction|sci[- ]?fi", re.I), "Science Fiction", 80),
    (re.compile(r"fantasy", re.I), "Fantasy", 80),
    (re.compile(r"romance", re.I), "Romance", 80),
    (re.compile(r"horror", re.I), "Horror", 80),
    (re.compile(r"historical fiction", re.I), "Historical Fiction", 80),
    (re.compile(r"biograph", re.I), "Biography", 75),
    (re.compile(r"memoir", re.I), "Memoir", 75),
    (re.compile(r"self[- ]help|conduct of life|self[- ]realization", re.I), "Self-Help", 85),
    (re.compile(r"literary", re.I), "Literary Fiction", 60),
    (re.compile(r"\bfiction\b", re.I), "Fiction", 50),
    (re.compile(r"novels?", re.I), "Fiction", 55),
    (re.compile(r"non[- ]?fiction", re.I), "Nonfiction", 80),
    (re.compile(r"business", re.I), "Business", 70),
    (re.compile(r"economics", re.I), "Economics", 65),
    (re.compile(r"philosophy", re.I), "Philosophy", 70),
    (re.compile(r"psychology", re.I), "Psychology", 70),
    (re.compile(r"history", re.I), "History", 65),
    (re.compile(r"politic", re.I), "Politics", 65),
    (re.compile(r"religion|spiritual", re.I), "Religion", 65),
    (re.compile(r"health", re.I), "Health", 65),
    (re.compile(r"travel", re.I), "Travel", 65),
    (re.compile(r"cook|food", re.I), "Cooking", 65),
    (re.compile(r"poetry", re.I), "Poetry", 65),
    (re.compile(r"\bdrama\b", re.I), "Drama", 65),
    (re.compile(r"young adult", re.I), "Young Adult", 75),
    (re.compile(r"children|juvenile", re.I), "Children's", 75),
    (re.compile(r"comic|graphic novel", re.I), "Comics and Graphic Novels", 75),
    (re.compile(r"technolog|computer", re.I), "Technology", 70),
    (re.compile(r"\bscience\b", re.I), "Science", 60),
)


def _normalize_label(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _is_denied(label: str) -> bool:
    normalized = _normalize_label(label)
    if not normalized or len(normalized) < 3:
        return True
    return any(pattern.search(normalized) for pattern in GENRE_DENY_PATTERNS)


def _map_label(label: str) -> list[tuple[str, int]]:
    normalized = _normalize_label(label)
    if not normalized or _is_denied(label):
        return []

    if normalized in _CANONICAL_BY_LOWER:
        return [(_CANONICAL_BY_LOWER[normalized], 100)]

    if normalized in GENRE_ALIASES:
        return [(GENRE_ALIASES[normalized], 95)]

    for alias in sorted(GENRE_ALIASES, key=len, reverse=True):
        if alias == normalized:
            continue
        if alias in normalized or normalized in alias:
            return [(GENRE_ALIASES[alias], 90)]

    matches: list[tuple[str, int]] = []
    for pattern, canonical, score in _KEYWORD_RULES:
        if pattern.search(normalized):
            matches.append((canonical, score))

    for canonical in CANONICAL_GENRES:
        canon_lower = canonical.lower()
        if canon_lower in normalized or normalized in canon_lower:
            matches.append((canonical, 85))

    return matches


_GENRE_PRIORITY: dict[str, int] = {
    "Thriller": 0,
    "Mystery": 1,
    "Crime": 2,
    "Horror": 3,
    "Science Fiction": 4,
    "Fantasy": 5,
    "Romance": 6,
    "Historical Fiction": 7,
    "Literary Fiction": 8,
    "Fiction": 9,
    "Nonfiction": 10,
}


def normalize_user_genre_name(name: str) -> str:
    """Normalize a user-entered genre name, using canonical casing when recognized."""
    cleaned = name.strip()
    if not cleaned:
        return ""
    normalized = _normalize_label(cleaned)
    if normalized in _CANONICAL_BY_LOWER:
        return _CANONICAL_BY_LOWER[normalized]
    if normalized in GENRE_ALIASES:
        return GENRE_ALIASES[normalized]
    return cleaned


def normalize_metadata_genres(raw_labels: list[str], *, max_genres: int = METADATA_GENRE_LIMIT) -> list[str]:
    """Return curated canonical genre names from provider subject/category labels."""
    scores: dict[str, int] = {}

    for raw in raw_labels:
        if not raw or not str(raw).strip():
            continue
        for canonical, score in _map_label(str(raw)):
            scores[canonical] = max(scores.get(canonical, 0), score)

    ordered = sorted(
        scores.items(),
        key=lambda item: (-item[1], _GENRE_PRIORITY.get(item[0], 50), item[0]),
    )
    return [name for name, _ in ordered[:max_genres]]
