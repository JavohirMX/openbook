from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class EnvelopePagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "per_page"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "data": data,
                "meta": {
                    "page": self.page.number,
                    "total": self.page.paginator.count,
                    "per_page": self.get_page_size(self.request),
                },
            }
        )
