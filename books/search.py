from django.db.models import Q

from books.models import _IS_POSTGRESQL


def book_text_search_q(value: str) -> Q:
    """Match books by title, author, ISBN, quotes, reviews, and private notes."""
    q = (
        Q(title__icontains=value)
        | Q(subtitle__icontains=value)
        | Q(authors__name__icontains=value)
        | Q(isbn_13=value)
        | Q(isbn_10=value)
        | Q(quotes__text__icontains=value)
        | Q(review__review_text__icontains=value)
        | Q(private_notes__text__icontains=value)
    )
    if _IS_POSTGRESQL:
        from django.contrib.postgres.search import SearchQuery

        q |= Q(search_vector=SearchQuery(value, config="english"))
    return q
