import pytest

from books.factories import BookAuthorFactory, BookFactory
from books.metadata_match import (
    LookupResult,
    score_candidate,
    score_candidate_data,
)


@pytest.mark.django_db
def test_score_candidate_high_for_matching_title_and_author():
    book = BookFactory(title="Dune")
    BookAuthorFactory(book=book, author__name="Frank Herbert")
    candidate = {"title": "Dune", "authors": ["Frank Herbert"]}
    score = score_candidate(book, candidate)
    assert score >= 0.82


@pytest.mark.django_db
def test_score_candidate_low_for_wrong_author():
    book = BookFactory(title="Dune")
    BookAuthorFactory(book=book, author__name="Frank Herbert")
    candidate = {"title": "Dune", "authors": ["Someone Else"]}
    score = score_candidate(book, candidate)
    assert score < 0.7


def test_score_candidate_data_for_import_row():
    ctx = {"title": "The Hobbit", "authors": ["J.R.R. Tolkien"]}
    candidate = {"title": "The Hobbit", "authors": ["J. R. R. Tolkien"]}
    score = score_candidate_data(ctx, candidate)
    assert score >= 0.8


def test_lookup_result_defaults():
    result = LookupResult(metadata={"title": "X"}, score=0.9, auto_apply=True)
    assert result.needs_review is False
    assert result.metadata["title"] == "X"
