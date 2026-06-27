from books.book_sort import DEFAULT_BOOK_SORT, SORT_CHOICES, resolve_book_sort

BOOK_VIEWS = ("list", "grid", "compact", "table")
DEFAULT_BOOK_VIEW = "list"


def resolve_book_view(request) -> str:
    raw = (request.GET.get("view") or request.POST.get("view") or "").strip().lower()
    return raw if raw in BOOK_VIEWS else DEFAULT_BOOK_VIEW


def book_list_paginate_by(view: str) -> int:
    return 24 if view == "grid" else 20


_FILTER_KEYS = ("shelf", "genre", "series", "status", "rating")


def books_active_filter_count(request) -> int:
    count = 0
    if request.GET.get("search", "").strip():
        count += 1
    for key in _FILTER_KEYS:
        if request.GET.get(key):
            count += 1
    sort = resolve_book_sort(request)
    if sort != DEFAULT_BOOK_SORT:
        count += 1
    return count


def books_filters_active(request) -> bool:
    return books_active_filter_count(request) > 0


class BookViewContextMixin:
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["book_view"] = resolve_book_view(self.request)
        ctx["sort_choices"] = SORT_CHOICES
        ctx["book_sort"] = resolve_book_sort(self.request)
        return ctx
