from django.db.models import Q
from rest_framework import serializers

from books.covers import cover_served_url, download_cover
from books.exceptions import DuplicateISBNError
from books.isbn import normalize_and_validate
from books.metadata import MetadataService
from books.models import Author, Book, BookNote, Genre, GenreSource, Quote, ReadingGoal, ReadingLog, ReadingProgress, Review, Series, Shelf, ReadingStatus, WebhookEndpoint
from books.services import (
    attach_authors_to_book,
    attach_genres_to_book,
    create_reading_log_for_book,
    get_or_create_genres,
    get_or_create_series,
)


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = ["id", "name", "sort_name"]


class AuthorDetailSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = Author
        fields = ["id", "name", "sort_name", "book_count", "created_at"]
        read_only_fields = fields

    def get_book_count(self, obj):
        return getattr(obj, "book_count", obj.book_authors.count())


class GenreDetailSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = Genre
        fields = ["id", "name", "slug", "source", "book_count", "created_at"]
        read_only_fields = ["id", "name", "slug", "source", "created_at"]

    def get_book_count(self, obj):
        return getattr(obj, "book_count", obj.book_genres.count())


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ["id", "name", "slug", "source"]


class SeriesSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = Series
        fields = ["id", "name", "slug", "sort_order", "book_count"]
        read_only_fields = ["id", "slug", "book_count"]

    def get_book_count(self, obj):
        return getattr(obj, "book_count", obj.books.count())


class GenreUpdateSerializer(serializers.ModelSerializer):
    merge_into = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Genre.objects.all(),
        write_only=True,
        required=False,
    )

    class Meta:
        model = Genre
        fields = ["name", "merge_into"]

    def validate_name(self, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise serializers.ValidationError("Genre name cannot be empty.")
        return value


class GenreDeleteSerializer(serializers.Serializer):
    reassign_to = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Genre.objects.all(),
        required=False,
        allow_null=True,
    )


class BookListSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=True)
    genres = GenreSerializer(many=True, read_only=True)
    series = SeriesSerializer(read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "subtitle",
            "isbn_13",
            "isbn_10",
            "cover_url",
            "authors",
            "genres",
            "series",
            "series_position",
            "status",
            "created_at",
        ]

    def get_status(self, obj):
        if hasattr(obj, "reading_log"):
            return obj.reading_log.status
        return ReadingStatus.NOT_STARTED

    def to_representation(self, instance):
        data = super().to_representation(instance)
        served = cover_served_url(instance, self.context.get("request"))
        if served:
            data["cover_url"] = served
        return data


class BookSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True, read_only=True)
    author_names = serializers.ListField(
        child=serializers.CharField(max_length=500),
        write_only=True,
        required=False,
    )
    genres = GenreSerializer(many=True, read_only=True)
    genre_names = serializers.ListField(
        child=serializers.CharField(max_length=100),
        write_only=True,
        required=False,
    )
    series = SeriesSerializer(read_only=True)
    series_slug = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Series.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )
    series_name = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        max_length=500,
    )
    status = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "subtitle",
            "isbn_13",
            "isbn_10",
            "pages",
            "published_year",
            "published_date",
            "publisher",
            "description",
            "cover_url",
            "openlibrary_work_id",
            "openlibrary_edition_key",
            "google_books_id",
            "language",
            "format",
            "owned",
            "narrator",
            "authors",
            "author_names",
            "genres",
            "genre_names",
            "series",
            "series_slug",
            "series_name",
            "series_position",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {
            "isbn_13": {"validators": []},
            "isbn_10": {"validators": []},
        }

    def get_status(self, obj):
        if hasattr(obj, "reading_log"):
            return obj.reading_log.status
        return ReadingStatus.NOT_STARTED

    def validate(self, attrs):
        isbn_13 = attrs.get("isbn_13")
        isbn_10 = attrs.get("isbn_10")

        if isbn_13 is not None or isbn_10 is not None:
            normalized_13, normalized_10, warnings = normalize_and_validate(
                isbn_13=isbn_13,
                isbn_10=isbn_10,
            )
            if normalized_13 is not None:
                attrs["isbn_13"] = normalized_13
            if normalized_10 is not None:
                attrs["isbn_10"] = normalized_10
            existing_warnings = self.context.setdefault("isbn_warnings", [])
            for warning in warnings:
                if warning not in existing_warnings:
                    existing_warnings.append(warning)

        return attrs

    def _resolve_series(self, validated_data, *, instance=None):
        series_name = validated_data.pop("series_name", None)
        series_slug_provided = "series_slug" in validated_data
        series_slug = validated_data.pop("series_slug", None)

        if series_slug_provided:
            return series_slug
        if series_name is not None:
            if series_name.strip():
                return get_or_create_series(series_name)
            return None
        if instance is not None:
            return instance.series
        return None

    def _find_duplicate_book(self, isbn_13, isbn_10):
        q = Q()
        if isbn_13:
            q |= Q(isbn_13=isbn_13)
        if isbn_10:
            q |= Q(isbn_10=isbn_10)
        if not q:
            return None
        return Book.all_objects.filter(q).first()

    def create(self, validated_data):
        author_names = validated_data.pop("author_names", [])
        genre_names = validated_data.pop("genre_names", [])
        series = self._resolve_series(validated_data)

        final_13 = validated_data.get("isbn_13")
        final_10 = validated_data.get("isbn_10")
        existing = self._find_duplicate_book(final_13, final_10)
        if existing:
            raise DuplicateISBNError(existing_book_id=existing.id)

        if not validated_data.get("cover_url") and validated_data.get("isbn_13"):
            metadata = MetadataService().lookup_isbn(validated_data["isbn_13"])
            if metadata.get("cover_url") and not validated_data.get("cover_url"):
                validated_data["cover_url"] = metadata["cover_url"]
            if metadata.get("pages") and not validated_data.get("pages"):
                validated_data["pages"] = metadata["pages"]
            if metadata.get("publisher") and not validated_data.get("publisher"):
                validated_data["publisher"] = metadata["publisher"]
            if metadata.get("genres") and not genre_names:
                genre_names = metadata["genres"]
            if metadata.get("authors") and not author_names:
                author_names = metadata["authors"]

        book = Book.objects.create(**validated_data, series=series)

        if author_names:
            attach_authors_to_book(book, author_names)
        if genre_names:
            genres = get_or_create_genres(genre_names, source=GenreSource.OPEN_LIBRARY)
            attach_genres_to_book(book, genres)

        create_reading_log_for_book(book)
        if book.cover_url:
            download_cover(book)
        return book

    def update(self, instance, validated_data):
        author_names = validated_data.pop("author_names", None)
        genre_names = validated_data.pop("genre_names", None)
        series = self._resolve_series(validated_data, instance=instance)
        old_cover_url = instance.cover_url

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.series = series
        instance.save()

        if author_names is not None:
            attach_authors_to_book(instance, author_names)
        if genre_names is not None:
            genres = get_or_create_genres(genre_names, source=GenreSource.USER)
            attach_genres_to_book(instance, genres)

        new_cover_url = validated_data.get("cover_url")
        if new_cover_url and new_cover_url != old_cover_url:
            download_cover(instance, force=True)
        elif instance.cover_url and not instance.cover_image:
            download_cover(instance)

        return instance

    def to_representation(self, instance):
        instance = (
            Book.objects.filter(pk=instance.pk)
            .prefetch_related("authors", "genres")
            .select_related("reading_log", "series")
            .first()
        ) or instance
        data = super().to_representation(instance)
        served = cover_served_url(instance, self.context.get("request"))
        if served:
            data["cover_url"] = served
        return data


class ShelfSerializer(serializers.ModelSerializer):
    book_count = serializers.SerializerMethodField()

    class Meta:
        model = Shelf
        fields = [
            "id",
            "name",
            "description",
            "color",
            "sort_order",
            "created_at",
            "book_count",
        ]
        read_only_fields = ["id", "created_at"]

    def get_book_count(self, obj):
        return getattr(obj, "book_count", 0)


class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = [
            "id",
            "rating",
            "review_text",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_rating(self, value):
        if value is not None and not 1 <= value <= 5:
            raise serializers.ValidationError("Rating must be between 1 and 5.")
        return value


class ReadingProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingProgress
        fields = [
            "id",
            "logged_on",
            "current_page",
            "progress_percent",
            "pages_read",
            "note",
            "created_at",
        ]
        read_only_fields = fields


class ReadingLogSerializer(serializers.ModelSerializer):
    progress_history = ReadingProgressSerializer(
        source="progress_entries",
        many=True,
        read_only=True,
    )

    class Meta:
        model = ReadingLog
        fields = [
            "id",
            "status",
            "current_page",
            "progress_percent",
            "total_pages",
            "read_count",
            "started_at",
            "finished_at",
            "updated_at",
            "progress_history",
        ]
        read_only_fields = fields


class ReadingLogUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=ReadingLog._meta.get_field("status").choices,
        required=False,
    )
    current_page = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    progress_percent = serializers.IntegerField(
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
    )
    pages_read = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    total_pages = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    note = serializers.CharField(max_length=280, required=False, allow_null=True, allow_blank=True)


class QuoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Quote
        fields = ["id", "text", "position", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class BookNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookNote
        fields = ["id", "text", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class ReadingGoalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReadingGoal
        fields = ["year", "target_books", "target_pages", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class WebhookEndpointSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookEndpoint
        fields = [
            "id",
            "url",
            "secret",
            "events",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
        extra_kwargs = {"secret": {"write_only": True, "required": False}}

    def validate_events(self, value):
        from books.webhooks import WEBHOOK_EVENTS

        if not value:
            raise serializers.ValidationError("Select at least one event.")
        invalid = [event for event in value if event not in WEBHOOK_EVENTS]
        if invalid:
            raise serializers.ValidationError(f"Unknown events: {', '.join(invalid)}")
        return value

    def create(self, validated_data):
        from books.webhooks import generate_webhook_secret

        if not validated_data.get("secret"):
            validated_data["secret"] = generate_webhook_secret()
        return super().create(validated_data)
