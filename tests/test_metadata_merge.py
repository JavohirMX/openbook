import pytest

from books.metadata_merge import merge_metadata_best_per_field


@pytest.mark.parametrize(
    "candidates,expected_cover",
    [
        (
            [
                {"cover_url": "https://books.google.com/thumbnail.jpg", "source": "google_books"},
                {
                    "cover_url": "https://covers.openlibrary.org/b/id/12345-L.jpg",
                    "source": "open_library",
                },
            ],
            "https://covers.openlibrary.org/b/id/12345-L.jpg",
        ),
        (
            [
                {"cover_url": "https://covers.openlibrary.org/b/isbn/9780000000000-L.jpg", "source": "open_library_isbn"},
                {"cover_url": "http://books.google.com/thumb", "source": "google_books"},
            ],
            "https://covers.openlibrary.org/b/isbn/9780000000000-L.jpg",
        ),
    ],
)
def test_merge_prefers_better_cover(candidates, expected_cover):
    merged = merge_metadata_best_per_field(*candidates)
    assert merged["cover_url"] == expected_cover


def test_merge_combines_genres_and_year():
    ol = {
        "title": "Dune",
        "authors": ["Frank Herbert"],
        "genres": ["Science Fiction"],
        "subjects": ["Science fiction"],
        "source": "open_library",
    }
    gb = {
        "published_year": "1965",
        "pages": 412,
        "publisher": "Ace",
        "description": "A long description from Google Books about Dune.",
        "source": "google_books",
    }
    merged = merge_metadata_best_per_field(ol, gb)
    assert merged["title"] == "Dune"
    assert merged["published_year"] == 1965
    assert merged["pages"] == 412
    assert merged["publisher"] == "Ace"
    assert "Science Fiction" in merged["genres"]
    assert "description" in merged


def test_merge_isbn_from_candidates():
    merged = merge_metadata_best_per_field(
        {"isbn_13": "9780143127741", "title": "Book", "source": "open_library"},
        {"isbn_10": "0143127748", "source": "google_books"},
    )
    assert merged["isbn_13"] == "9780143127741"
    assert merged["isbn_10"] == "0143127748"


def test_merge_authors_respects_book_context():
    merged = merge_metadata_best_per_field(
        {"authors": ["Other Person"], "source": "google_books"},
        {"authors": ["Frank Herbert"], "source": "open_library"},
        book_context={"authors": ["Frank Herbert"]},
    )
    assert merged["authors"][0] == "Frank Herbert"


def test_merge_provider_ids():
    merged = merge_metadata_best_per_field(
        {
            "openlibrary_work_id": "/works/OL123W",
            "openlibrary_edition_key": "/books/OL456M",
            "source": "open_library",
        },
        {"google_books_id": "gb123", "wikidata_id": "Q42", "source": "google_books"},
    )
    assert merged["openlibrary_work_id"] == "/works/OL123W"
    assert merged["google_books_id"] == "gb123"
    assert merged["wikidata_id"] == "Q42"
    assert "google_books" in merged["source_summary"]
