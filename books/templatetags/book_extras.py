from urllib.parse import urlencode

from django import template

register = template.Library()

BOOK_LIST_QUERY_KEYS = (
    "search",
    "shelf",
    "genre",
    "series",
    "status",
    "rating",
    "sort",
    "view",
    "page",
)


@register.simple_tag(takes_context=True)
def book_query(context, **overrides):
    request = context.get("request")
    if not request:
        return ""
    params = {}
    for key in BOOK_LIST_QUERY_KEYS:
        if key in overrides:
            value = overrides[key]
            if value is not None and value != "":
                params[key] = value
        elif key in request.GET and request.GET.get(key):
            params[key] = request.GET.get(key)
    return urlencode(params)
