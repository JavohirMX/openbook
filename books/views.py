from django.db.models import Count
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from books.filters import BookFilter
from books.isbn import normalize_isbn
from books.metadata import MetadataService
from books.models import Book, BookshelfItem, ReadingLog, Review, Shelf
from books.reading_service import update_reading_log
from books.serializers import (
    BookListSerializer,
    BookSerializer,
    ReadingLogSerializer,
    ReadingLogUpdateSerializer,
    ReviewSerializer,
    ShelfSerializer,
)
from books.stats import compute_stats


class ShelfViewSet(viewsets.ModelViewSet):
    queryset = Shelf.objects.annotate(book_count=Count("bookshelf_items")).order_by(
        "sort_order", "name"
    )
    serializer_class = ShelfSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


class StatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(compute_stats())


class BookViewSet(viewsets.ModelViewSet):
    filterset_class = BookFilter
    ordering_fields = ["title", "created_at", "-created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, "action", None) == "trash":
            return (
                Book.all_objects.filter(deleted_at__isnull=False)
                .prefetch_related("authors", "genres")
                .select_related("reading_log")
                .order_by("-deleted_at")
            )

        return (
            Book.objects.prefetch_related("authors", "genres")
            .select_related("reading_log")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return BookListSerializer
        return BookSerializer

    def _response_with_warnings(self, serializer, data, status_code=status.HTTP_200_OK, headers=None):
        warnings = serializer.context.get("isbn_warnings", [])
        payload = {"data": data}
        if warnings:
            payload["meta"] = {"warnings": warnings}
        return Response(payload, status=status_code, headers=headers)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return self._response_with_warnings(
            serializer,
            serializer.data,
            status_code=status.HTTP_201_CREATED,
            headers=headers,
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return self._response_with_warnings(serializer, serializer.data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        permanent = request.query_params.get("permanent", "").lower() == "true"
        if permanent:
            instance.delete()
        else:
            instance.deleted_at = timezone.now()
            instance.save(update_fields=["deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="lookup")
    def lookup(self, request):
        isbn = request.query_params.get("isbn")
        if not isbn:
            raise ValidationError({"isbn": ["This query parameter is required."]})

        normalized = normalize_isbn(isbn)
        if not normalized or not normalized.isbn_13:
            raise ValidationError({"isbn": ["Invalid ISBN format."]})

        metadata = MetadataService().lookup_isbn(normalized.isbn_13)
        return Response(metadata)

    @action(detail=False, methods=["get"], url_path="trash")
    def trash(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response({"data": serializer.data})

    @action(detail=True, methods=["post"], url_path="restore")
    def restore(self, request, pk=None):
        book = Book.all_objects.filter(pk=pk, deleted_at__isnull=False).first()
        if book is None:
            raise NotFound("Book not found in trash.")

        book.deleted_at = None
        book.save(update_fields=["deleted_at"])

        serializer = BookSerializer(book, context=self.get_serializer_context())
        return Response({"data": serializer.data})

    @action(detail=True, methods=["post"], url_path="shelve")
    def shelve(self, request, pk=None):
        book = self.get_object()
        shelf_id = request.data.get("shelf_id")
        if shelf_id is None:
            raise ValidationError({"shelf_id": ["This field is required."]})

        try:
            shelf = Shelf.objects.get(pk=shelf_id)
        except Shelf.DoesNotExist as exc:
            raise NotFound("Shelf not found.") from exc

        BookshelfItem.objects.get_or_create(book=book, shelf=shelf)
        return Response({"book_id": str(book.pk), "shelf_id": shelf.pk})

    @action(detail=True, methods=["post"], url_path="unshelve")
    def unshelve(self, request, pk=None):
        book = self.get_object()
        shelf_id = request.data.get("shelf_id")
        if shelf_id is None:
            raise ValidationError({"shelf_id": ["This field is required."]})

        deleted, _ = BookshelfItem.objects.filter(book=book, shelf_id=shelf_id).delete()
        if not deleted:
            raise NotFound("Book is not on this shelf.")
        return Response({"book_id": str(book.pk), "shelf_id": shelf_id})

    @action(detail=True, methods=["get", "put", "delete"], url_path="review")
    def review(self, request, pk=None):
        book = self.get_object()

        if request.method == "GET":
            try:
                review = book.review
            except Review.DoesNotExist as exc:
                raise NotFound("Review not found.") from exc
            return Response(ReviewSerializer(review).data)

        if request.method == "PUT":
            serializer = ReviewSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            review, _created = Review.objects.update_or_create(
                book=book,
                defaults=serializer.validated_data,
            )
            return Response(ReviewSerializer(review).data)

        review = getattr(book, "review", None)
        if review is None:
            raise NotFound("Review not found.")
        review.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get", "put"], url_path="reading")
    def reading(self, request, pk=None):
        book = self.get_object()
        reading_log, _created = ReadingLog.objects.get_or_create(
            book=book,
            defaults={"total_pages": book.pages},
        )

        if request.method == "GET":
            return Response(ReadingLogSerializer(reading_log).data)

        serializer = ReadingLogUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        update_reading_log(reading_log, serializer.validated_data)
        reading_log.refresh_from_db()
        return Response(ReadingLogSerializer(reading_log).data)
