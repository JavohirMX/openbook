import pytest
from django.test import RequestFactory

from books.book_view import books_active_filter_count, books_filters_active


@pytest.mark.parametrize(
    "query,expected",
    [
        ({}, False),
        ({"search": "  "}, False),
        ({"search": "dune"}, True),
        ({"status": "reading"}, True),
        ({"sort": "title"}, True),
        ({"sort": "-created_at"}, False),
        ({"view": "grid"}, False),
    ],
)
def test_books_filters_active(query, expected):
    request = RequestFactory().get("/books/", query)
    assert books_filters_active(request) is expected
    assert (books_active_filter_count(request) > 0) is expected
