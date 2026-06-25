import pytest

from books.genre_normalize import CANONICAL_GENRES, normalize_metadata_genres

DRAGON_TATTOO_SUBJECTS = [
    "heiresses",
    "aristocracy",
    "secrecy",
    "finance",
    "child sexual abuse",
    "Book of Leviticus",
    "rape",
    "Misogyny",
    "Novels",
    "Fiction: Literature",
    "Fiction, thrillers",
    "Crime",
]

SUBTLE_ART_SUBJECTS = [
    "Long Now Manual for Civilization",
    "New York Times bestseller",
    "nyt:advice-how-to-and-miscellaneous=2016-10-02",
    "Conducta de vida",
    "Conduct of life",
    "Self-realization",
]

SILENT_PATIENT_SUBJECTS = [
    "Marriage",
    "Fiction",
    "Family violence",
    "Fiction, thrillers, general",
    "New York Times bestseller",
    "Marriage, fiction",
    "Artists, fiction",
    "London (england), fiction",
    "Fiction, thrillers",
    "Fiction, psychological",
]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('=""', []),
        (["nyt:foo", "heiresses"], []),
        (["Conduct of life", "nyt:tag"], ["Self-Help"]),
        (["Fiction, thrillers"], ["Thriller"]),
        (["Novels"], ["Fiction"]),
    ],
)
def test_normalize_edge_cases(raw, expected):
    labels = raw if isinstance(raw, list) else [raw]
    assert normalize_metadata_genres(labels) == expected


def test_dragon_tattoo_subjects():
    result = normalize_metadata_genres(DRAGON_TATTOO_SUBJECTS)
    assert "Crime" in result
    assert "Thriller" in result
    assert "Fiction" in result or "Literary Fiction" in result
    assert "heiresses" not in result
    assert "Book of Leviticus" not in result
    assert not any("nyt" in g.lower() for g in result)
    assert len(result) <= 3
    assert all(g in CANONICAL_GENRES for g in result)


def test_subtle_art_subjects():
    result = normalize_metadata_genres(SUBTLE_ART_SUBJECTS)
    assert result == ["Self-Help"]
    assert "New York Times bestseller" not in result


def test_silent_patient_subjects():
    result = normalize_metadata_genres(SILENT_PATIENT_SUBJECTS)
    assert "Thriller" in result
    assert "Fiction" in result
    assert "Marriage, fiction" not in result
    assert "London (england), fiction" not in result
    assert len(result) <= 3


def test_respects_max_genres():
    raw = ["Fiction", "Thriller", "Crime", "Mystery", "Horror"]
    assert len(normalize_metadata_genres(raw, max_genres=2)) == 2
