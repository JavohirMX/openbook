from types import SimpleNamespace

import pytest

from books.book_sort import DEFAULT_BOOK_SORT, apply_book_sort, resolve_book_sort
from books.factories import BookFactory
from books.models import Book


def _request(sort=None):
    params = {}
    if sort is not None:
        params["sort"] = sort
    return SimpleNamespace(GET=params, POST={})


def test_resolve_book_sort_default():
    assert resolve_book_sort(_request()) == DEFAULT_BOOK_SORT


def test_resolve_book_sort_valid():
    assert resolve_book_sort(_request("title")) == "title"
    assert resolve_book_sort(_request("-finished_at")) == "-finished_at"


def test_resolve_book_sort_invalid():
    assert resolve_book_sort(_request("bogus")) == DEFAULT_BOOK_SORT


@pytest.mark.django_db
def test_apply_book_sort_title():
    BookFactory(title="Zebra Sort Book")
    BookFactory(title="Alpha Sort Book")
    titles = list(apply_book_sort(Book.objects.all(), "title").values_list("title", flat=True))
    assert titles.index("Alpha Sort Book") < titles.index("Zebra Sort Book")


@pytest.mark.django_db
def test_apply_book_sort_reverse_title():
    BookFactory(title="Zebra Reverse Book")
    BookFactory(title="Alpha Reverse Book")
    titles = list(apply_book_sort(Book.objects.all(), "-title").values_list("title", flat=True))
    assert titles.index("Zebra Reverse Book") < titles.index("Alpha Reverse Book")
