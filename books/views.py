from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
import json
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from books.filters import BookFilter
from books.isbn import normalize_isbn
from books.metadata import MetadataService
from books.models import Author, Book, BookNote, BookshelfItem, Genre, Quote, ReadingGoal, ReadingLog, Review, Series, Shelf, WebhookEndpoint
from books.provider_links import book_provider_links
from books.reading_service import update_reading_log
from books.reading_timeline import build_reading_timeline
from books.serializers import (
    AuthorDetailSerializer,
    AuthorSerializer,
    BookListSerializer,
    BookNoteSerializer,
    BookSerializer,
    GenreDeleteSerializer,
    GenreDetailSerializer,
    GenreSerializer,
    GenreUpdateSerializer,
    QuoteSerializer,
    ReadingLogSerializer,
    ReadingLogUpdateSerializer,
    ReviewSerializer,
    ReadingGoalSerializer,
    SeriesSerializer,
    ShelfSerializer,
    WebhookEndpointSerializer,
)
from books.services import delete_genre, merge_genres, rename_genre
from books.stats import compute_stats


class AuthorViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AuthorSerializer

    def get_queryset(self):
        from django.db.models import Count

        qs = Author.objects.annotate(book_count=Count("book_authors")).order_by("name")
        search = self.request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AuthorDetailSerializer
        return AuthorSerializer


class GenreViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = GenreSerializer
    lookup_field = "slug"
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        from django.db.models import Count

        return Genre.objects.annotate(book_count=Count("book_genres")).order_by("name")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return GenreDetailSerializer
        if self.action in ("partial_update", "update"):
            return GenreUpdateSerializer
        if self.action == "destroy":
            return GenreDeleteSerializer
        return GenreSerializer

    def partial_update(self, request, *args, **kwargs):
        genre = self.get_object()
        serializer = GenreUpdateSerializer(genre, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        merge_into = serializer.validated_data.pop("merge_into", None)
        if merge_into is not None:
            genre = merge_genres(genre, merge_into)
            return Response(GenreDetailSerializer(genre).data)

        new_name = serializer.validated_data.get("name")
        if new_name is not None:
            genre = rename_genre(genre, new_name)
        return Response(GenreDetailSerializer(genre).data)

    def destroy(self, request, *args, **kwargs):
        genre = self.get_object()
        serializer = GenreDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reassign_to = serializer.validated_data.get("reassign_to")
        try:
            delete_genre(genre, reassign_to=reassign_to)
        except ValueError as exc:
            raise ValidationError({"detail": str(exc)}) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = SeriesSerializer
    lookup_field = "slug"

    def get_queryset(self):
        from django.db.models import Count

        return Series.objects.annotate(book_count=Count("books")).order_by("sort_order", "name")


class ShelfViewSet(viewsets.ModelViewSet):
    queryset = Shelf.objects.annotate(book_count=Count("bookshelf_items")).order_by(
        "sort_order", "name"
    )
    serializer_class = ShelfSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


class ReadingGoalViewSet(viewsets.ModelViewSet):
    queryset = ReadingGoal.objects.all()
    serializer_class = ReadingGoalSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "year"


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
            .select_related("reading_log", "series")
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

    @action(detail=False, methods=["get"], url_path="search-metadata")
    def search_metadata(self, request):
        query = request.query_params.get("q", "").strip()
        if not query:
            raise ValidationError({"q": ["This query parameter is required."]})
        limit = min(int(request.query_params.get("limit", 10)), 25)
        results = MetadataService().search_books(query, limit=limit)
        return Response({"results": results})

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

    @action(detail=True, methods=["get"], url_path="reading/history")
    def reading_history(self, request, pk=None):
        book = self.get_object()
        reading_log = getattr(book, "reading_log", None)
        timeline = [entry.as_dict() for entry in build_reading_timeline(reading_log)]
        return Response({"book_id": str(book.pk), "events": timeline})

    @action(detail=True, methods=["get", "post"], url_path="quotes")
    def quotes(self, request, pk=None):
        book = self.get_object()

        if request.method == "GET":
            quotes = book.quotes.all()
            return Response(QuoteSerializer(quotes, many=True).data)

        serializer = QuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quote = serializer.save(book=book)
        return Response(QuoteSerializer(quote).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "put", "delete"], url_path="note")
    def note(self, request, pk=None):
        book = self.get_object()

        if request.method == "GET":
            note = book.private_notes.first()
            if note is None:
                raise NotFound("Note not found.")
            return Response(BookNoteSerializer(note).data)

        if request.method == "PUT":
            serializer = BookNoteSerializer(data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            note, _created = BookNote.objects.update_or_create(
                book=book,
                defaults=serializer.validated_data,
            )
            return Response(BookNoteSerializer(note).data)

        deleted, _ = book.private_notes.all().delete()
        if not deleted:
            raise NotFound("Note not found.")
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="provider-links")
    def provider_links(self, request, pk=None):
        book = self.get_object()
        return Response({"links": book_provider_links(book)})


class QuoteViewSet(viewsets.ModelViewSet):
    serializer_class = QuoteSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return Quote.objects.select_related("book").order_by("-created_at")


class ImportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from books.import_jobs import create_csv_preview_job, create_isbn_job, confirm_csv_job, serialize_job

        if "file" in request.FILES:
            job = create_csv_preview_job(request.user, request.FILES["file"])
            if request.data.get("confirm") in (True, "true", "1", 1):
                confirm_csv_job(job)
        elif "isbns" in request.data:
            isbns = request.data["isbns"]
            if isinstance(isbns, str):
                isbns = [line.strip() for line in isbns.splitlines() if line.strip()]
            job = create_isbn_job(request.user, isbns)
        else:
            raise ValidationError({"detail": "Provide 'isbns' array or CSV 'file'."})

        return Response(serialize_job(job, request=request), status=status.HTTP_202_ACCEPTED)


class ImportBackfillView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from books.import_jobs import create_metadata_backfill_job, serialize_job
        from books.library_maintenance import books_needing_metadata

        book_ids = request.data.get("book_ids")
        if book_ids is None:
            book_ids = [str(pk) for pk in books_needing_metadata().values_list("pk", flat=True)]
        elif isinstance(book_ids, str):
            book_ids = [line.strip() for line in book_ids.splitlines() if line.strip()]
        else:
            book_ids = [str(book_id) for book_id in book_ids if book_id]

        if not book_ids:
            raise ValidationError({"book_ids": ["No books eligible for metadata backfill."]})

        job = create_metadata_backfill_job(request.user, book_ids)
        return Response(serialize_job(job, request=request), status=status.HTTP_202_ACCEPTED)


class ImportJobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from books.import_jobs import confirm_csv_job, serialize_job
        from books.models import ImportJob, ImportJobStatus

        job = ImportJob.objects.filter(pk=pk, user=request.user).first()
        if not job:
            raise NotFound("Import job not found.")

        if (
            request.query_params.get("confirm") in ("true", "1")
            and job.status == ImportJobStatus.AWAITING_CONFIRMATION
        ):
            confirm_csv_job(job)

        return Response(serialize_job(job, request=request))

    def post(self, request, pk):
        from books.import_jobs import request_cancel_import_job, serialize_job
        from books.models import ImportJob

        job = ImportJob.objects.filter(pk=pk, user=request.user).first()
        if not job:
            raise NotFound("Import job not found.")

        try:
            request_cancel_import_job(job)
        except ValueError as exc:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"detail": str(exc)}) from exc

        job.refresh_from_db()
        return Response(serialize_job(job, request=request))


class ExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from books.import_export import export_csv, export_json

        fmt = request.query_params.get("format", "json")
        if fmt == "csv":
            content = export_csv()
            response = HttpResponse(content, content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="openbook-export.csv"'
            return response

        data = export_json()
        response = HttpResponse(
            json.dumps(data, indent=2),
            content_type="application/json",
        )
        response["Content-Disposition"] = 'attachment; filename="openbook-export.json"'
        return response


class EmbedView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        from books.embed import embed_payload
        from accounts.models import UserProfile

        key = request.query_params.get("key", "").strip()
        kind = request.query_params.get("kind", "currently_reading")
        if kind not in ("currently_reading", "recently_finished"):
            raise ValidationError({"kind": ["Must be 'currently_reading' or 'recently_finished'."]})

        profile = UserProfile.objects.filter(embed_enabled=True, embed_key=key).first()
        if not profile:
            return Response({"error": "Invalid or disabled embed key."}, status=status.HTTP_403_FORBIDDEN)

        return Response(embed_payload(kind=kind, request=request))


class WebhookEndpointViewSet(viewsets.ModelViewSet):
    queryset = WebhookEndpoint.objects.all()
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
