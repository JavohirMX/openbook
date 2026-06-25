import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

_IS_POSTGRESQL = "postgresql" in settings.DATABASES["default"]["ENGINE"]

if _IS_POSTGRESQL:
    from django.contrib.postgres.indexes import GinIndex
    from django.contrib.postgres.search import SearchVectorField


class AuthorRole(models.TextChoices):
    AUTHOR = "author", "Author"
    EDITOR = "editor", "Editor"
    TRANSLATOR = "translator", "Translator"
    ILLUSTRATOR = "illustrator", "Illustrator"


class GenreSource(models.TextChoices):
    OPEN_LIBRARY = "open_library", "Open Library"
    USER = "user", "User"


class ReadingStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    READING = "reading", "Currently Reading"
    FINISHED = "finished", "Finished"
    PAUSED = "paused", "Paused"
    ABANDONED = "abandoned", "DNF"


class ActiveBookManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


_BOOK_INDEXES = [
    models.Index(fields=["-created_at"], name="idx_book_created"),
    models.Index(
        fields=["-created_at"],
        name="idx_book_active",
        condition=Q(deleted_at__isnull=True),
    ),
]
if _IS_POSTGRESQL:
    _BOOK_INDEXES += [
        GinIndex(fields=["search_vector"], name="idx_book_search"),
        GinIndex(
            fields=["title"],
            name="idx_book_title_trgm",
            opclasses=["gin_trgm_ops"],
        ),
    ]


class Book(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500)
    subtitle = models.CharField(max_length=500, blank=True, null=True)
    isbn_13 = models.CharField(max_length=13, null=True, blank=True)
    isbn_10 = models.CharField(max_length=10, null=True, blank=True)
    pages = models.PositiveIntegerField(null=True, blank=True)
    published_year = models.SmallIntegerField(null=True, blank=True)
    published_date = models.DateField(null=True, blank=True)
    publisher = models.CharField(max_length=500, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    cover_url = models.URLField(max_length=2000, blank=True, null=True)
    language = models.CharField(max_length=10, default="en", blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    authors = models.ManyToManyField("Author", through="BookAuthor")
    genres = models.ManyToManyField("Genre", through="BookGenre", blank=True)

    objects = ActiveBookManager()
    all_objects = models.Manager()

    if _IS_POSTGRESQL:
        search_vector = SearchVectorField(null=True, editable=False)
    else:
        search_vector = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        indexes = _BOOK_INDEXES
        constraints = [
            models.UniqueConstraint(
                fields=["isbn_13"],
                condition=Q(isbn_13__isnull=False),
                name="idx_book_isbn_13",
            ),
            models.UniqueConstraint(
                fields=["isbn_10"],
                condition=Q(isbn_10__isnull=False),
                name="idx_book_isbn_10",
            ),
        ]

    def __str__(self):
        return self.title


class Author(models.Model):
    name = models.CharField(max_length=500)
    sort_name = models.CharField(max_length=500, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["name"], name="idx_author_name"),
            models.Index(fields=["sort_name"], name="idx_author_sort_name"),
        ]

    def __str__(self):
        return self.name


class BookAuthor(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="book_authors")
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="book_authors")
    role = models.CharField(
        max_length=50,
        choices=AuthorRole.choices,
        default=AuthorRole.AUTHOR,
        blank=True,
        null=True,
    )
    position = models.SmallIntegerField(default=0)

    class Meta:
        indexes = [
            models.Index(fields=["book"], name="idx_bookauthor_book"),
            models.Index(fields=["author"], name="idx_bookauthor_author"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "author", "role"],
                name="books_bookauthor_book_author_role_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.book} — {self.author} ({self.role})"


class Genre(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    source = models.CharField(
        max_length=20,
        choices=GenreSource.choices,
        default=GenreSource.USER,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["slug"], name="idx_genre_slug"),
            models.Index(fields=["name"], name="idx_genre_name"),
        ]

    def __str__(self):
        return self.name


class BookGenre(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="book_genres")
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name="book_genres")

    class Meta:
        indexes = [
            models.Index(fields=["book"], name="idx_bookgenre_book"),
            models.Index(fields=["genre"], name="idx_bookgenre_genre"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "genre"],
                name="books_bookgenre_book_genre_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.book} — {self.genre}"


class Shelf(models.Model):
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True, null=True)
    color = models.CharField(max_length=7, blank=True, null=True)
    sort_order = models.SmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class BookshelfItem(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="bookshelf_items")
    shelf = models.ForeignKey(Shelf, on_delete=models.CASCADE, related_name="bookshelf_items")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["book"], name="idx_bsi_book"),
            models.Index(fields=["shelf"], name="idx_bsi_shelf"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["book", "shelf"],
                name="books_bookshelfitem_book_shelf_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.book} on {self.shelf}"


class Review(models.Model):
    book = models.OneToOneField(Book, on_delete=models.CASCADE, related_name="review")
    rating = models.SmallIntegerField(null=True, blank=True)
    review_text = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["book"], name="idx_review_book"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__isnull=True)
                | (Q(rating__gte=1) & Q(rating__lte=5)),
                name="books_review_rating_range",
            ),
        ]

    def __str__(self):
        if self.rating is not None:
            return f"{self.book} — {self.rating}/5"
        return str(self.book)


class ReadingLog(models.Model):
    book = models.OneToOneField(Book, on_delete=models.CASCADE, related_name="reading_log")
    status = models.CharField(
        max_length=20,
        choices=ReadingStatus.choices,
        default=ReadingStatus.NOT_STARTED,
    )
    current_page = models.PositiveIntegerField(null=True, blank=True)
    progress_percent = models.SmallIntegerField(null=True, blank=True)
    total_pages = models.PositiveIntegerField(null=True, blank=True)
    read_count = models.SmallIntegerField(default=0)
    started_at = models.DateField(null=True, blank=True)
    finished_at = models.DateField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["book"], name="idx_reading_book"),
            models.Index(fields=["status"], name="idx_reading_status"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(progress_percent__isnull=True)
                | (Q(progress_percent__gte=0) & Q(progress_percent__lte=100)),
                name="books_readinglog_progress_percent_range",
            ),
        ]

    def __str__(self):
        return f"{self.book} — {self.get_status_display()}"


class ReadingProgress(models.Model):
    reading_log = models.ForeignKey(
        ReadingLog,
        on_delete=models.CASCADE,
        related_name="progress_entries",
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reading_progress")
    logged_on = models.DateField(default=timezone.localdate)
    current_page = models.PositiveIntegerField(null=True, blank=True)
    progress_percent = models.SmallIntegerField(null=True, blank=True)
    pages_read = models.PositiveIntegerField(null=True, blank=True)
    note = models.CharField(max_length=280, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["reading_log"], name="idx_progress_log"),
            models.Index(fields=["book", "logged_on"], name="idx_progress_book_date"),
            models.Index(fields=["logged_on"], name="idx_progress_logged_on"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(progress_percent__isnull=True)
                | (Q(progress_percent__gte=0) & Q(progress_percent__lte=100)),
                name="books_readingprogress_progress_percent_range",
            ),
        ]

    def __str__(self):
        return f"{self.book} — {self.logged_on}"
