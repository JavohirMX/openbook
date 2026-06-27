from django.db.models import Min

DEFAULT_BOOK_SORT = "-created_at"

SORT_CHOICES = [
    ("-created_at", "Recently added"),
    ("title", "Title A–Z"),
    ("-title", "Title Z–A"),
    ("author", "Author A–Z"),
    ("-finished_at", "Recently finished"),
]

VALID_SORTS = {value for value, _ in SORT_CHOICES}


def resolve_book_sort(request) -> str:
    raw = (request.GET.get("sort") or request.POST.get("sort") or "").strip()
    if raw in VALID_SORTS:
        return raw
    return DEFAULT_BOOK_SORT


def apply_book_sort(qs, sort):
    if sort == "title":
        return qs.order_by("title")
    if sort == "-title":
        return qs.order_by("-title")
    if sort == "author":
        return qs.annotate(primary_author=Min("authors__name")).order_by("primary_author", "title")
    if sort == "-finished_at":
        return qs.order_by("-reading_log__finished_at", "-created_at")
    return qs.order_by("-created_at")


def books_for_page(qs, request):
    return apply_book_sort(qs, resolve_book_sort(request))
