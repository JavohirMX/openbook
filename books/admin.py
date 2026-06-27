from django.contrib import admin

from books.models import (
    Author,
    Book,
    BookAuthor,
    BookGenre,
    BookNote,
    BookshelfItem,
    Genre,
    ImportJob,
    MetadataMatchProposal,
    Quote,
    ReadingLog,
    ReadingProgress,
    Review,
    Series,
    Shelf,
    WebhookEndpoint,
)


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "isbn_13", "isbn_10", "format", "owned", "published_year", "language", "deleted_at", "created_at")
    list_filter = ("language", "format", "owned", "deleted_at")
    search_fields = ("title", "subtitle", "isbn_13", "isbn_10", "publisher")
    readonly_fields = ("id", "search_vector", "created_at", "updated_at")


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_name", "created_at")
    search_fields = ("name", "sort_name")


@admin.register(BookAuthor)
class BookAuthorAdmin(admin.ModelAdmin):
    list_display = ("book", "author", "role", "position")
    list_filter = ("role",)
    search_fields = ("book__title", "author__name")
    autocomplete_fields = ("book", "author")


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "sort_order")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "source", "created_at")
    list_filter = ("source",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(BookGenre)
class BookGenreAdmin(admin.ModelAdmin):
    list_display = ("book", "genre")
    search_fields = ("book__title", "genre__name")
    autocomplete_fields = ("book", "genre")


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    list_display = ("name", "color", "sort_order", "created_at")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(BookshelfItem)
class BookshelfItemAdmin(admin.ModelAdmin):
    list_display = ("book", "shelf", "added_at")
    list_filter = ("shelf",)
    search_fields = ("book__title", "shelf__name")
    autocomplete_fields = ("book", "shelf")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("book", "rating", "created_at", "updated_at")
    list_filter = ("rating",)
    search_fields = ("book__title", "review_text")
    autocomplete_fields = ("book",)


@admin.register(ReadingLog)
class ReadingLogAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "status",
        "progress_percent",
        "current_page",
        "read_count",
        "started_at",
        "finished_at",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("book__title",)
    autocomplete_fields = ("book",)


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "user", "progress_done", "progress_total", "created_at")
    list_filter = ("kind", "status")
    readonly_fields = (
        "id",
        "user",
        "kind",
        "status",
        "csv_file",
        "isbns",
        "preview",
        "progress_done",
        "progress_total",
        "result",
        "error_message",
        "created_at",
        "started_at",
        "finished_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MetadataMatchProposal)
class MetadataMatchProposalAdmin(admin.ModelAdmin):
    list_display = ("book", "score", "status", "source_summary", "created_at")
    list_filter = ("status",)
    search_fields = ("book__title", "source_summary")
    readonly_fields = ("id", "created_at", "updated_at")
    autocomplete_fields = ("book",)


@admin.register(BookNote)
class BookNoteAdmin(admin.ModelAdmin):
    list_display = ("book", "updated_at")
    search_fields = ("book__title", "text")
    autocomplete_fields = ("book",)


@admin.register(Quote)
class QuoteAdmin(admin.ModelAdmin):
    list_display = ("book", "position", "created_at")
    search_fields = ("book__title", "text")
    autocomplete_fields = ("book",)


@admin.register(ReadingProgress)
class ReadingProgressAdmin(admin.ModelAdmin):
    list_display = (
        "book",
        "logged_on",
        "progress_percent",
        "current_page",
        "pages_read",
        "created_at",
    )
    list_filter = ("logged_on",)
    search_fields = ("book__title", "note")
    autocomplete_fields = ("reading_log", "book")
    date_hierarchy = "logged_on"


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("url", "enabled", "created_at")
    list_filter = ("enabled",)
    readonly_fields = ("id", "created_at", "updated_at")
