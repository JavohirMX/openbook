from django.db.models import Q
from django_filters import rest_framework as filters

from books.isbn import normalize_isbn
from books.models import Book, _IS_POSTGRESQL


class BookFilter(filters.FilterSet):
    author = filters.CharFilter(field_name="authors__name", lookup_expr="iexact")
    isbn = filters.CharFilter(method="filter_isbn")
    shelf = filters.NumberFilter(field_name="bookshelf_items__shelf_id")
    genre = filters.CharFilter(method="filter_genre")
    status = filters.CharFilter(field_name="reading_log__status")
    search = filters.CharFilter(method="filter_search")

    class Meta:
        model = Book
        fields = ["author", "isbn", "shelf", "genre", "status"]

    def filter_isbn(self, queryset, name, value):
        normalized = normalize_isbn(value)
        if not normalized:
            return queryset.none()
        q = Q()
        if normalized.isbn_13:
            q |= Q(isbn_13=normalized.isbn_13)
        if normalized.isbn_10:
            q |= Q(isbn_10=normalized.isbn_10)
        return queryset.filter(q)

    def filter_genre(self, queryset, name, value):
        return queryset.filter(Q(genres__slug=value) | Q(genres__name__iexact=value))

    def filter_search(self, queryset, name, value):
        if not value:
            return queryset

        normalized = normalize_isbn(value)
        if normalized:
            isbn_q = Q()
            if normalized.isbn_13:
                isbn_q |= Q(isbn_13=normalized.isbn_13)
            if normalized.isbn_10:
                isbn_q |= Q(isbn_10=normalized.isbn_10)
            isbn_matches = queryset.filter(isbn_q)
            if isbn_matches.exists():
                return isbn_matches

        if _IS_POSTGRESQL:
            from django.contrib.postgres.search import SearchQuery, SearchRank

            query = SearchQuery(value, config="english")
            return (
                queryset.annotate(rank=SearchRank("search_vector", query))
                .filter(Q(search_vector=query) | Q(authors__name__icontains=value))
                .distinct()
                .order_by("-rank")
            )

        return queryset.filter(
            Q(title__icontains=value)
            | Q(subtitle__icontains=value)
            | Q(authors__name__icontains=value)
        ).distinct()
