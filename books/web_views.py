import json

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView
from accounts.models import ApiToken, UserProfile

from accounts.forms import PasswordChangeForm, ProfileForm
from books.book_view import BookViewContextMixin, book_list_paginate_by, books_filters_active, books_active_filter_count, resolve_book_view
from books.forms import (
    BookFilterForm,
    BookForm,
    BookNoteForm,
    GenreManageForm,
    CSVImportForm,
    ISBNImportForm,
    QuoteForm,
    ReadingGoalForm,
    ReadingUpdateForm,
    ReviewForm,
    SORT_CHOICES,
    ShelveForm,
    ShelfForm,
)
from books.import_export import export_csv, export_json
from books.import_jobs import (
    confirm_csv_job,
    create_csv_preview_job,
    create_isbn_job,
    create_metadata_backfill_job,
    request_cancel_import_job,
)
from books.import_worker import schedule_import_processing
from books.library_maintenance import (
    apply_health_missing_filter,
    books_needing_metadata,
    clear_metadata_cache,
    find_duplicate_groups,
    library_health_stats,
    merge_books,
    refresh_book_metadata,
)
from books.metadata import MetadataService
from books.metadata_match import LookupResult, apply_lookup_result, lookup_for_book
from books.models import (
    Author,
    Book,
    BookNote,
    BookshelfItem,
    BookTag,
    BookTaggedItem,
    FilterPreset,
    Genre,
    ImportJob,
    ImportJobKind,
    ImportJobStatus,
    MetadataMatchProposal,
    MetadataMatchProposalStatus,
    Quote,
    ReadingGoal,
    ReadingLog,
    ReadingStatus,
    Review,
    Series,
    Shelf,
    WebhookEndpoint,
    _IS_POSTGRESQL,
)
from books.provider_links import book_provider_links
from books.reading_timeline import build_reading_timeline
from books.reading_service import update_reading_log
from books.search import book_text_search_q
from books.services import (
    attach_authors_to_book,
    attach_genres_to_book,
    create_reading_log_for_book,
    delete_genre,
    merge_genres,
    merge_authors,
    find_duplicate_author_groups,
    rename_genre,
)
from books.stats import (
    books_finished_on,
    compute_stats,
    compute_year_review,
    finish_calendar_strip,
    genres_for_filter,
    monthly_reads_for_year,
    pages_per_month_for_year,
    parse_stats_period,
    parse_stats_year_month,
    stats_available_years,
)
from books.status_shelves import get_status_shelf, get_status_shelves


METADATA_LOCK_FIELDS = [
    "title",
    "description",
    "pages",
    "publisher",
    "published_year",
    "isbn_13",
    "isbn_10",
    "cover_url",
    "authors",
    "genres",
]


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "books/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["currently_reading"] = (
            ReadingLog.objects.filter(status=ReadingStatus.READING)
            .select_related("book")
            .prefetch_related("book__authors")[:6]
        )
        stats = compute_stats()
        ctx["stats"] = stats
        ctx["finished_count"] = next(
            (s["count"] for s in stats["books_by_status"] if s["status"] == "finished"), 0
        )
        ctx["reading_count"] = next(
            (s["count"] for s in stats["books_by_status"] if s["status"] == "reading"), 0
        )
        ctx["recent_books"] = (
            Book.objects.prefetch_related("authors")
            .order_by("-created_at")[:5]
        )
        ctx["shelf_count"] = Shelf.objects.count()
        ctx["metrics_items"] = [
            {"value": stats["total_books"], "label": "Books"},
            {"value": ctx["finished_count"], "label": "Read"},
            {"value": ctx["reading_count"], "label": "Reading"},
            {"value": ctx["shelf_count"], "label": "Shelves"},
        ]
        ctx["reading_goal"] = stats.get("reading_goal")
        ctx["reading_streak"] = stats.get("reading_streak", 0)
        health = library_health_stats()
        ctx["library_health"] = health
        ctx["show_health_nudge"] = (
            health.get("missing_cover", 0) > 0 or health.get("pending_metadata_matches", 0) > 0
        )
        ctx["up_next"] = (
            Book.objects.filter(reading_log__status=ReadingStatus.NOT_STARTED)
            .prefetch_related("authors")
            .order_by("-created_at")[:5]
        )
        return ctx


def _save_book_contributors(form, book):
    attach_authors_to_book(
        book,
        form.get_author_list(),
        editors=form.get_role_list("editor_names"),
        translators=form.get_role_list("translator_names"),
        illustrators=form.get_role_list("illustrator_names"),
    )


def _filter_books(request):
    qs = Book.objects.prefetch_related("authors", "genres").select_related("reading_log", "review", "series")
    form = BookFilterForm(request.GET or None)
    search = request.GET.get("search", "").strip()
    shelf_id = request.GET.get("shelf")
    genre_id = request.GET.get("genre")
    series_param = request.GET.get("series")
    status = request.GET.get("status")
    rating = request.GET.get("rating")
    sort = request.GET.get("sort", "-created_at")
    missing = request.GET.get("missing")

    if search:
        if _IS_POSTGRESQL:
            from django.contrib.postgres.search import SearchQuery, SearchRank

            query = SearchQuery(search, config="english")
            qs = (
                qs.filter(book_text_search_q(search))
                .annotate(rank=SearchRank("search_vector", query))
                .distinct()
            )
            if sort == "-created_at":
                qs = qs.order_by("-rank", "-created_at")
            else:
                qs = _apply_book_sort(qs, sort)
        else:
            qs = qs.filter(book_text_search_q(search)).distinct()
            qs = _apply_book_sort(qs, sort)
    else:
        qs = _apply_book_sort(qs, sort)

    if shelf_id:
        qs = qs.filter(bookshelf_items__shelf_id=shelf_id)
    if genre_id:
        qs = qs.filter(book_genres__genre_id=genre_id)
    if series_param:
        if str(series_param).isdigit():
            qs = qs.filter(series_id=series_param)
        else:
            qs = qs.filter(series__slug=series_param)
    if status:
        qs = qs.filter(reading_log__status=status)
    if rating:
        qs = qs.filter(review__rating=rating)
    if missing:
        qs = apply_health_missing_filter(qs, missing)
    tag_slug = request.GET.get("tag")
    if tag_slug:
        qs = qs.filter(tagged_items__tag__slug=tag_slug)

    return qs, form


def _apply_book_sort(qs, sort):
    from django.db.models import Min

    if sort == "title":
        return qs.order_by("title")
    if sort == "-title":
        return qs.order_by("-title")
    if sort == "author":
        return qs.annotate(primary_author=Min("authors__name")).order_by("primary_author", "title")
    if sort == "-finished_at":
        return qs.order_by("-reading_log__finished_at", "-created_at")
    return qs.order_by("-created_at")


class BookListView(BookViewContextMixin, LoginRequiredMixin, ListView):
    template_name = "books/list.html"
    context_object_name = "books"
    paginate_by = 20

    def get_queryset(self):
        self.filter_form = BookFilterForm(self.request.GET or None)
        qs, _ = _filter_books(self.request)
        return qs

    def get_paginate_by(self, queryset):
        return book_list_paginate_by(resolve_book_view(self.request))

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["books/partials/book_rows.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        ctx["shelves"] = Shelf.objects.all()
        ctx["genres"] = genres_for_filter()
        from django.db.models import Count

        ctx["series_list"] = Series.objects.annotate(book_count=Count("books")).order_by("sort_order", "name")
        ctx["reading_statuses"] = ReadingStatus.choices
        ctx["sort_choices"] = SORT_CHOICES
        ctx["bulk_shelves"] = Shelf.objects.all()
        ctx["filters_active"] = books_filters_active(self.request)
        ctx["active_filter_count"] = books_active_filter_count(self.request)
        ctx["filter_presets"] = FilterPreset.objects.all()
        ctx["book_tags"] = BookTag.objects.all()
        return ctx


@login_required
def save_filter_preset(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    name = (request.POST.get("name") or "").strip()
    if not name:
        messages.error(request, "Preset name is required.")
        return redirect("web:book-list")
    allowed = {"search", "shelf", "genre", "series", "status", "rating", "sort", "missing", "tag"}
    query_parts = []
    for key in allowed:
        value = request.POST.get(key) or request.GET.get(key)
        if value:
            query_parts.append(f"{key}={value}")
    FilterPreset.objects.update_or_create(
        name=name,
        defaults={"query_string": "&".join(query_parts)},
    )
    messages.success(request, f'Saved filter preset "{name}".')
    return redirect("web:book-list")


@login_required
def delete_filter_preset(request, pk):
    if request.method == "POST":
        FilterPreset.objects.filter(pk=pk).delete()
        messages.success(request, "Filter preset deleted.")
    return redirect("web:book-list")


@login_required
def books_bulk_action(request):
    if request.method != "POST":
        return HttpResponse(status=405)

    book_ids = request.POST.getlist("book_ids")
    action = request.POST.get("bulk_action")

    if not book_ids:
        messages.warning(request, "Select at least one book.")
        return redirect("web:book-list")

    books = list(Book.objects.filter(pk__in=book_ids))
    if not books:
        messages.warning(request, "No matching books found.")
        return redirect("web:book-list")

    if action == "soft_delete":
        now = timezone.now()
        for book in books:
            book.deleted_at = now
            book.save(update_fields=["deleted_at"])
        messages.success(request, f"Moved {len(books)} book(s) to trash.")
    elif action == "set_status":
        status_value = request.POST.get("status")
        if status_value not in ReadingStatus.values:
            messages.error(request, "Choose a valid reading status.")
            return redirect("web:book-list")
        updated = 0
        for book in books:
            log = create_reading_log_for_book(book)
            update_reading_log(log, {"status": status_value})
            updated += 1
        messages.success(request, f"Updated status for {updated} book(s).")
    elif action == "add_shelf":
        shelf_id = request.POST.get("shelf_id")
        try:
            shelf = Shelf.objects.get(pk=shelf_id)
        except (Shelf.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Choose a valid shelf.")
            return redirect("web:book-list")
        added = 0
        for book in books:
            _, created = BookshelfItem.objects.get_or_create(book=book, shelf=shelf)
            if created:
                added += 1
        messages.success(request, f"Added {added} book(s) to {shelf.name}.")
    else:
        messages.error(request, "Unknown bulk action.")

    if request.headers.get("HX-Request"):
        qs, _ = _filter_books(request)
        view = resolve_book_view(request)
        paginator = Paginator(qs, book_list_paginate_by(view))
        page_number = request.POST.get("page") or request.GET.get("page") or 1
        page_obj = paginator.get_page(page_number)
        return render(
            request,
            "books/partials/book_rows.html",
            {
                "books": page_obj.object_list,
                "page_obj": page_obj,
                "request": request,
                "bulk_shelves": Shelf.objects.all(),
                "book_view": view,
            },
        )

    return redirect("web:book-list")


class BookDetailView(LoginRequiredMixin, DetailView):
    model = Book
    template_name = "books/detail.html"
    context_object_name = "book"

    def get_queryset(self):
        return Book.objects.prefetch_related("authors", "genres", "bookshelf_items__shelf").select_related(
            "reading_log", "review", "series"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        book = self.object
        try:
            review = book.review
        except Review.DoesNotExist:
            review = None
        ctx["review_form"] = ReviewForm(instance=review)
        log = getattr(book, "reading_log", None)
        if log:
            ctx["reading_form"] = ReadingUpdateForm(
                initial={
                    "status": log.status,
                    "progress_percent": log.progress_percent,
                    "current_page": log.current_page,
                }
            )
            ctx["reading_log"] = log
        else:
            ctx["reading_form"] = ReadingUpdateForm(initial={"status": ReadingStatus.NOT_STARTED})
            ctx["reading_log"] = None
        ctx["shelve_form"] = ShelveForm()
        ctx["all_shelves"] = Shelf.objects.all()
        ctx["book_shelves"] = Shelf.objects.filter(bookshelf_items__book=book)
        ctx["provider_links"] = book_provider_links(book)
        from books.library_maintenance import metadata_missing_fields

        ctx["metadata_missing_fields"] = metadata_missing_fields(book)
        ctx["reading_timeline"] = build_reading_timeline(log)
        ctx["quote_form"] = QuoteForm()
        ctx["quotes"] = book.quotes.all()[:20]
        note = book.private_notes.first()
        ctx["note_form"] = BookNoteForm(instance=note)
        ctx["book_tags"] = BookTag.objects.filter(tagged_items__book=book)
        ctx["all_book_tags"] = BookTag.objects.all()
        ctx["metadata_lock_fields"] = METADATA_LOCK_FIELDS
        ctx["metadata_locked_fields"] = book.metadata_locked_fields or []
        primary_author = book.authors.first()
        if primary_author:
            ctx["same_author_books"] = (
                Book.objects.filter(authors=primary_author)
                .exclude(pk=book.pk)
                .prefetch_related("authors")[:6]
            )
        primary_genre = book.genres.first()
        if primary_genre:
            ctx["same_genre_books"] = (
                Book.objects.filter(genres=primary_genre)
                .exclude(pk=book.pk)
                .prefetch_related("authors")[:6]
            )
        ctx["tbr_short_books"] = (
            Book.objects.filter(reading_log__status=ReadingStatus.NOT_STARTED, pages__lte=250)
            .exclude(pk=book.pk)
            .prefetch_related("authors")[:5]
        )
        return ctx


class BookCreateView(LoginRequiredMixin, CreateView):
    model = Book
    form_class = BookForm
    template_name = "books/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Add Book"
        return ctx

    def form_valid(self, form):
        book = form.save(commit=False)
        isbn_13 = form.cleaned_data.get("isbn_13")
        isbn_10 = form.cleaned_data.get("isbn_10")
        book.isbn_13 = isbn_13
        book.isbn_10 = isbn_10
        book.save()
        _save_book_contributors(form, book)
        genres = form.cleaned_data.get("genres")
        if genres:
            attach_genres_to_book(book, list(genres))
        create_reading_log_for_book(book)
        if book.cover_url:
            download_cover(book)
        warnings = getattr(form, "isbn_warnings", [])
        for w in warnings:
            messages.warning(self.request, w)
        messages.success(self.request, f'"{book.title}" added.')
        return redirect("web:book-detail", pk=book.pk)


class BookUpdateView(LoginRequiredMixin, UpdateView):
    model = Book
    form_class = BookForm
    template_name = "books/form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = "Edit Book"
        return ctx

    def form_valid(self, form):
        book = form.save(commit=False)
        old_cover_url = self.object.cover_url
        book.isbn_13 = form.cleaned_data.get("isbn_13")
        book.isbn_10 = form.cleaned_data.get("isbn_10")
        book.save()
        _save_book_contributors(form, book)
        genres = form.cleaned_data.get("genres")
        if genres is not None:
            attach_genres_to_book(book, list(genres))
        new_cover_url = form.cleaned_data.get("cover_url")
        if new_cover_url and new_cover_url != old_cover_url:
            download_cover(book, force=True)
        elif book.cover_url and not book.cover_image:
            download_cover(book)
        warnings = getattr(form, "isbn_warnings", [])
        for w in warnings:
            messages.warning(self.request, w)
        messages.success(self.request, f'"{book.title}" updated.')
        return redirect("web:book-detail", pk=book.pk)


@login_required
def isbn_lookup(request):
    isbn = request.GET.get("isbn", "").strip()
    if not isbn:
        return render(request, "books/partials/lookup_status.html", {"message": "Enter an ISBN to look up."})

    meta = MetadataService().lookup_isbn(isbn)
    if not meta:
        return render(
            request,
            "books/partials/lookup_status.html",
            {"message": "No metadata found. Enter details manually."},
        )

    return render(request, "books/partials/form_fields_prefill.html", {"meta": meta, "isbn": isbn})


@login_required
def epub_metadata_lookup(request):
    upload = request.FILES.get("epub_file")
    if not upload:
        return render(request, "books/partials/lookup_status.html", {"message": "Choose an EPUB or OPF file."})
    meta = extract_metadata_from_upload(upload)
    if not meta.get("title") and not meta.get("authors"):
        return render(
            request,
            "books/partials/lookup_status.html",
            {"message": "Could not read metadata from that file."},
        )
    return render(request, "books/partials/form_fields_prefill.html", {"meta": meta, "isbn": meta.get("isbn_13") or meta.get("isbn_10") or ""})


@login_required
def metadata_search(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return render(
            request,
            "books/partials/metadata_search_results.html",
            {"results": [], "query": ""},
        )
    results = MetadataService().search_books(query, limit=10)
    return render(
        request,
        "books/partials/metadata_search_results.html",
        {"results": results, "query": query},
    )


@login_required
def book_quote(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        form = QuoteForm(request.POST)
        if form.is_valid():
            form.save(book=book)
            messages.success(request, "Quote saved.")
    return redirect("web:book-detail", pk=pk)


@login_required
def book_quote_delete(request, pk, quote_id):
    book = get_object_or_404(Book, pk=pk)
    quote = get_object_or_404(Quote, pk=quote_id, book=book)
    if request.method == "POST":
        quote.delete()
        messages.success(request, "Quote deleted.")
    return redirect("web:book-detail", pk=pk)


@login_required
def book_note(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        note = book.private_notes.first()
        form = BookNoteForm(request.POST, instance=note)
        if form.is_valid():
            note = form.save(commit=False)
            note.book = book
            note.save()
            messages.success(request, "Private note saved.")
    return redirect("web:book-detail", pk=pk)


@login_required
def book_soft_delete(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        book.deleted_at = timezone.now()
        book.save(update_fields=["deleted_at"])
        messages.success(request, f'"{book.title}" moved to trash.')
        return redirect("web:book-list")
    return redirect("web:book-detail", pk=pk)


class ShelfListView(LoginRequiredMixin, ListView):
    model = Shelf
    template_name = "shelves/list.html"
    context_object_name = "shelves"

    def get_queryset(self):
        from django.db.models import Count

        return Shelf.objects.annotate(book_count=Count("bookshelf_items")).order_by("sort_order", "name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["shelf_form"] = ShelfForm()
        ctx["status_shelves"] = get_status_shelves()
        return ctx

    def post(self, request, *args, **kwargs):
        form = ShelfForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Shelf created.")
            return redirect("web:shelf-list")
        self.object_list = self.get_queryset()
        ctx = self.get_context_data()
        ctx["shelf_form"] = form
        return render(request, self.template_name, ctx)


class ShelfDetailView(BookViewContextMixin, LoginRequiredMixin, DetailView):
    model = Shelf
    template_name = "shelves/detail.html"
    context_object_name = "shelf"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["books"] = (
            Book.objects.filter(bookshelf_items__shelf=self.object)
            .prefetch_related("authors")
            .select_related("reading_log", "review")
        )
        ctx["shelf_form"] = ShelfForm(instance=self.object)
        return ctx


class AuthorListView(LoginRequiredMixin, ListView):
    model = Author
    template_name = "authors/list.html"
    context_object_name = "authors"
    paginate_by = 50

    def get_queryset(self):
        from django.db.models import Count

        qs = Author.objects.annotate(book_count=Count("book_authors")).order_by("name")
        search = self.request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class AuthorDetailView(LoginRequiredMixin, DetailView):
    model = Author
    template_name = "authors/detail.html"
    context_object_name = "author"

    def get_queryset(self):
        from django.db.models import Count

        return Author.objects.annotate(book_count=Count("book_authors"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["books"] = (
            Book.objects.filter(authors=self.object)
            .prefetch_related("authors")
            .select_related("reading_log", "review")
            .order_by("title")
        )
        return ctx


@login_required
def author_refresh_wikipedia(request, pk):
    author = get_object_or_404(Author, pk=pk)
    if request.method == "POST":
        data = fetch_author_wikipedia(author.name)
        if data:
            author.bio = data.get("bio") or author.bio
            author.wikipedia_url = data.get("wikipedia_url") or author.wikipedia_url
            author.photo_url = data.get("photo_url") or author.photo_url
            author.save(update_fields=["bio", "wikipedia_url", "photo_url"])
            messages.success(request, f'Updated Wikipedia data for "{author.name}".')
        else:
            messages.warning(request, "No Wikipedia article found for this author.")
    return redirect("web:author-detail", pk=pk)


class GenreListView(LoginRequiredMixin, ListView):
    model = Genre
    template_name = "genres/list.html"
    context_object_name = "genres"
    paginate_by = 50

    def get_queryset(self):
        from django.db.models import Count

        qs = Genre.objects.annotate(book_count=Count("book_genres")).order_by("name")
        search = self.request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class GenreDetailView(BookViewContextMixin, LoginRequiredMixin, DetailView):
    model = Genre
    template_name = "genres/detail.html"
    context_object_name = "genre"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        from django.db.models import Count

        return Genre.objects.annotate(book_count=Count("book_genres"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["books"] = (
            Book.objects.filter(genres=self.object)
            .prefetch_related("authors", "genres")
            .select_related("reading_log", "review")
            .order_by("title")
        )
        manage_form = GenreManageForm(initial={"name": self.object.name})
        other_genres = Genre.objects.exclude(pk=self.object.pk).order_by("name")
        manage_form.fields["merge_into"].queryset = other_genres
        manage_form.fields["reassign_to"].queryset = other_genres
        ctx["manage_form"] = manage_form
        return ctx

    def post(self, request, *args, **kwargs):
        genre = self.get_object()
        action = request.POST.get("action")
        manage_form = GenreManageForm(request.POST)
        other_genres = Genre.objects.exclude(pk=genre.pk).order_by("name")
        manage_form.fields["merge_into"].queryset = other_genres
        manage_form.fields["reassign_to"].queryset = other_genres

        if action == "rename" and manage_form.is_valid():
            new_name = (manage_form.cleaned_data.get("name") or "").strip()
            if new_name and new_name != genre.name:
                try:
                    updated = rename_genre(genre, new_name)
                    messages.success(request, f'Renamed genre to “{updated.name}”.')
                    return redirect("web:genre-detail", slug=updated.slug)
                except ValueError as exc:
                    messages.error(request, str(exc))
            elif not new_name:
                messages.error(request, "Enter a new genre name.")

        if action == "merge" and manage_form.is_valid():
            target = manage_form.cleaned_data.get("merge_into")
            if target:
                try:
                    merged = merge_genres(genre, target)
                    messages.success(request, f'Merged into “{merged.name}”.')
                    return redirect("web:genre-detail", slug=merged.slug)
                except ValueError as exc:
                    messages.error(request, str(exc))
            else:
                messages.error(request, "Select a genre to merge into.")

        if action == "delete" and manage_form.is_valid():
            reassign_to = manage_form.cleaned_data.get("reassign_to")
            genre_name = genre.name
            try:
                delete_genre(genre, reassign_to=reassign_to)
                messages.success(request, f'Deleted genre “{genre_name}”.')
                return redirect("web:genre-list")
            except ValueError as exc:
                messages.error(request, str(exc))

        return redirect("web:genre-detail", slug=genre.slug)


class SeriesListView(LoginRequiredMixin, ListView):
    model = Series
    template_name = "series/list.html"
    context_object_name = "series_list"
    paginate_by = 50

    def get_queryset(self):
        from django.db.models import Count

        qs = Series.objects.annotate(book_count=Count("books")).order_by("sort_order", "name")
        search = self.request.GET.get("search", "").strip()
        if search:
            qs = qs.filter(name__icontains=search)
        return qs


class SeriesDetailView(BookViewContextMixin, LoginRequiredMixin, DetailView):
    model = Series
    template_name = "series/detail.html"
    context_object_name = "series"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        from django.db.models import Count

        return Series.objects.annotate(book_count=Count("books"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["books"] = (
            Book.objects.filter(series=self.object)
            .prefetch_related("authors")
            .select_related("reading_log", "review", "series")
            .order_by("series_position", "title")
        )
        return ctx


class StatusShelfDetailView(BookViewContextMixin, LoginRequiredMixin, TemplateView):
    template_name = "shelves/status_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_shelf = get_status_shelf(self.kwargs["slug"])
        ctx["status_shelf"] = status_shelf
        ctx["books"] = (
            Book.objects.filter(reading_log__status=status_shelf.status)
            .prefetch_related("authors")
            .select_related("reading_log", "review")
        )
        return ctx


@login_required
def header_search(request):
    from django.http import QueryDict

    search = request.GET.get("search", "").strip()
    books = []
    if search:
        params = QueryDict(mutable=True)
        params["search"] = search
        fake_request = type("R", (), {"GET": params})()
        qs, _ = _filter_books(fake_request)
        books = list(qs[:8])
    return render(request, "books/partials/header_search_results.html", {"books": books})


@login_required
def shelf_update(request, pk):
    shelf = get_object_or_404(Shelf, pk=pk)
    if request.method == "POST":
        form = ShelfForm(request.POST, instance=shelf)
        if form.is_valid():
            form.save()
            messages.success(request, "Shelf updated.")
    return redirect("web:shelf-detail", pk=pk)


@login_required
def shelf_delete(request, pk):
    shelf = get_object_or_404(Shelf, pk=pk)
    if request.method == "POST":
        shelf.delete()
        messages.success(request, "Shelf deleted.")
        return redirect("web:shelf-list")
    return redirect("web:shelf-detail", pk=pk)


@login_required
def shelf_reorder(request):
    if request.method != "POST":
        return redirect("web:shelf-list")

    shelf_ids = request.POST.getlist("shelf_ids")
    if not shelf_ids:
        if request.headers.get("HX-Request"):
            return HttpResponse(status=400)
        messages.error(request, "No shelves to reorder.")
        return redirect("web:shelf-list")

    valid_ids = []
    for raw_id in shelf_ids:
        try:
            valid_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    shelves_by_id = Shelf.objects.in_bulk(valid_ids)
    updates = []
    for index, shelf_id in enumerate(valid_ids):
        shelf = shelves_by_id.get(shelf_id)
        if shelf and shelf.sort_order != index:
            shelf.sort_order = index
            updates.append(shelf)

    if updates:
        Shelf.objects.bulk_update(updates, ["sort_order"])

    if request.headers.get("HX-Request"):
        return HttpResponse(status=204)
    messages.success(request, "Shelf order updated.")
    return redirect("web:shelf-list")


@login_required
def book_shelve(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        form = ShelveForm(request.POST)
        if form.is_valid():
            BookshelfItem.objects.get_or_create(book=book, shelf=form.cleaned_data["shelf"])
            messages.success(request, "Book added to shelf.")
    if request.headers.get("HX-Request"):
        return render(
            request,
            "books/partials/shelves_section.html",
            {"book": book, "book_shelves": Shelf.objects.filter(bookshelf_items__book=book), "shelve_form": ShelveForm()},
        )
    return redirect("web:book-detail", pk=pk)


@login_required
def book_unshelve(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        shelf_id = request.POST.get("shelf_id")
        BookshelfItem.objects.filter(book=book, shelf_id=shelf_id).delete()
        messages.success(request, "Book removed from shelf.")
    if request.headers.get("HX-Request"):
        return render(
            request,
            "books/partials/shelves_section.html",
            {"book": book, "book_shelves": Shelf.objects.filter(bookshelf_items__book=book), "shelve_form": ShelveForm()},
        )
    return redirect("web:book-detail", pk=pk)


@login_required
def book_review(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "DELETE" or request.POST.get("_method") == "DELETE":
        Review.objects.filter(book=book).delete()
        messages.success(request, "Review deleted.")
        return redirect("web:book-detail", pk=pk)

    if request.method in ("POST", "PUT"):
        review, _ = Review.objects.get_or_create(book=book)
        form = ReviewForm(request.POST, instance=review)
        if form.is_valid():
            form.save()
            messages.success(request, "Review saved.")
    return redirect("web:book-detail", pk=pk)


@login_required
def book_reading(request, pk):
    book = get_object_or_404(Book, pk=pk)
    log, _ = ReadingLog.objects.get_or_create(
        book=book, defaults={"status": ReadingStatus.NOT_STARTED}
    )
    if request.method in ("POST", "PUT"):
        form = ReadingUpdateForm(request.POST)
        if form.is_valid():
            data = {"status": form.cleaned_data["status"]}
            if form.cleaned_data.get("progress_percent") is not None:
                data["progress_percent"] = form.cleaned_data["progress_percent"]
            if form.cleaned_data.get("current_page") is not None:
                data["current_page"] = form.cleaned_data["current_page"]
            if form.cleaned_data.get("pages_read") is not None:
                data["pages_read"] = form.cleaned_data["pages_read"]
            if form.cleaned_data.get("note"):
                data["note"] = form.cleaned_data["note"]
            update_reading_log(log, data)
            messages.success(request, "Reading progress updated.")
    if request.headers.get("HX-Request"):
        log.refresh_from_db()
        return render(
            request,
            "books/partials/reading_section.html",
            {"book": book, "reading_form": ReadingUpdateForm(initial={
                "status": log.status,
                "progress_percent": log.progress_percent,
                "current_page": log.current_page,
            }), "reading_log": log},
        )
    return redirect("web:book-detail", pk=pk)


class TrashListView(BookViewContextMixin, LoginRequiredMixin, ListView):
    template_name = "trash/list.html"
    context_object_name = "books"
    paginate_by = 20

    def get_queryset(self):
        return Book.all_objects.filter(deleted_at__isnull=False).prefetch_related("authors").order_by("-deleted_at")


@login_required
def trash_restore(request, pk):
    book = get_object_or_404(Book.all_objects, pk=pk, deleted_at__isnull=False)
    if request.method == "POST":
        book.deleted_at = None
        book.save(update_fields=["deleted_at"])
        messages.success(request, f'"{book.title}" restored.')
    return redirect("web:trash-list")


@login_required
def trash_delete_permanent(request, pk):
    book = get_object_or_404(Book.all_objects, pk=pk, deleted_at__isnull=False)
    if request.method == "POST":
        title = book.title
        book.delete()
        messages.success(request, f'"{title}" permanently deleted.')
    return redirect("web:trash-list")


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "settings/settings.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        from accounts.embed import ensure_embed_key

        ctx["profile_form"] = ProfileForm(instance=profile, user=self.request.user)
        ctx["password_form"] = PasswordChangeForm(user=self.request.user)
        ctx["api_tokens"] = ApiToken.objects.filter(user=self.request.user)
        ctx["new_token"] = self.request.session.pop("new_token", None)
        ctx["new_token_label"] = self.request.session.pop("new_token_label", None)
        ctx["embed_enabled"] = profile.embed_enabled
        ctx["embed_key"] = ensure_embed_key(profile) if profile.embed_enabled else profile.embed_key
        ctx["embed_base_url"] = self.request.build_absolute_uri("/")[:-1]
        from books.webhooks import WEBHOOK_EVENTS

        ctx["webhooks"] = WebhookEndpoint.objects.all()
        ctx["webhook_events"] = WEBHOOK_EVENTS
        ctx["new_webhook_secret"] = self.request.session.pop("new_webhook_secret", None)
        ctx["reading_goals"] = ReadingGoal.objects.all()
        ctx["reading_goal_form"] = ReadingGoalForm(
            initial={"year": timezone.localdate().year},
        )
        from django.conf import settings as django_settings

        from books.metadata_hardcover import hardcover_enabled
        from books.metadata_isbndb import isbndb_enabled

        ctx["metadata_config"] = {
            "openlibrary_contact": bool(django_settings.OPENLIBRARY_CONTACT_EMAIL),
            "google_books_key": bool(getattr(django_settings, "GOOGLE_BOOKS_API_KEY", "")),
            "wikidata_enabled": django_settings.METADATA_WIKIDATA_ENABLED,
            "hardcover_enabled": hardcover_enabled(),
            "hardcover_configured": bool(getattr(django_settings, "HARDCOVER_API_TOKEN", "")),
            "isbndb_enabled": isbndb_enabled(),
            "import_enrichment": django_settings.IMPORT_GOODREADS_ENRICH_METADATA,
            "lookup_strategy": django_settings.METADATA_LOOKUP_STRATEGY,
        }
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "create_token":
            label = (request.POST.get("label") or "").strip()
            if not label:
                messages.error(request, "Token label is required.")
                return redirect("web:settings")
            token = ApiToken.create_for_user(request.user, label=label)
            request.session["new_token"] = token.key
            request.session["new_token_label"] = token.label
            messages.success(request, f'API token "{label}" created. Copy it now — it will not be shown again.')
            return redirect("web:settings")

        if action == "revoke_token":
            token_id = request.POST.get("token_id")
            deleted, _ = ApiToken.objects.filter(pk=token_id, user=request.user).delete()
            if deleted:
                messages.success(request, "API token revoked.")
            else:
                messages.error(request, "Token not found.")
            return redirect("web:settings")

        if action == "update_embed":
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            from accounts.embed import ensure_embed_key

            profile.embed_enabled = request.POST.get("embed_enabled") == "on"
            if profile.embed_enabled and not profile.embed_key:
                ensure_embed_key(profile)
            profile.save(update_fields=["embed_enabled", "embed_key"])
            messages.success(request, "Embed settings updated.")
            return redirect("web:settings")

        if action == "regenerate_embed_key":
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            from accounts.embed import ensure_embed_key

            profile.embed_key = ""
            ensure_embed_key(profile)
            messages.success(request, "Embed key regenerated.")
            return redirect("web:settings")

        if action == "update_profile":
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            form = ProfileForm(request.POST, instance=profile, user=request.user)
            if form.is_valid():
                form.save()
                messages.success(request, "Profile updated.")
            else:
                messages.error(request, "Please correct the errors below.")
                ctx = self.get_context_data()
                ctx["profile_form"] = form
                return render(request, self.template_name, ctx)

        if action == "change_password":
            form = PasswordChangeForm(user=request.user, data=request.POST)
            if form.is_valid():
                form.save()
                from django.contrib.auth import update_session_auth_hash

                update_session_auth_hash(request, form.user)
                messages.success(request, "Password updated.")
            else:
                messages.error(request, "Please correct the password errors below.")
                ctx = self.get_context_data()
                ctx["password_form"] = form
                return render(request, self.template_name, ctx)

        if action == "create_webhook":
            from books.webhooks import WEBHOOK_EVENTS, generate_webhook_secret

            url = (request.POST.get("url") or "").strip()
            events = request.POST.getlist("events")
            if not url:
                messages.error(request, "Webhook URL is required.")
                return redirect("web:settings")
            invalid = [event for event in events if event not in WEBHOOK_EVENTS]
            if invalid or not events:
                messages.error(request, "Select at least one valid event.")
                return redirect("web:settings")
            secret = generate_webhook_secret()
            WebhookEndpoint.objects.create(url=url, secret=secret, events=events)
            request.session["new_webhook_secret"] = secret
            messages.success(request, "Webhook created. Copy the signing secret now.")
            return redirect("web:settings")

        if action == "toggle_webhook":
            webhook_id = request.POST.get("webhook_id")
            webhook = WebhookEndpoint.objects.filter(pk=webhook_id).first()
            if webhook:
                webhook.enabled = not webhook.enabled
                webhook.save(update_fields=["enabled", "updated_at"])
                state = "enabled" if webhook.enabled else "disabled"
                messages.success(request, f"Webhook {state}.")
            return redirect("web:settings")

        if action == "delete_webhook":
            webhook_id = request.POST.get("webhook_id")
            deleted, _ = WebhookEndpoint.objects.filter(pk=webhook_id).delete()
            if deleted:
                messages.success(request, "Webhook deleted.")
            return redirect("web:settings")

        if action == "save_reading_goal":
            goal_id = request.POST.get("goal_id")
            instance = ReadingGoal.objects.filter(pk=goal_id).first() if goal_id else None
            form = ReadingGoalForm(request.POST, instance=instance)
            if form.is_valid():
                form.save()
                messages.success(request, f"Reading goal for {form.cleaned_data['year']} saved.")
            else:
                messages.error(request, "Please correct the reading goal errors.")
                ctx = self.get_context_data()
                ctx["reading_goal_form"] = form
                return render(request, self.template_name, ctx)
            return redirect("web:settings")

        if action == "delete_reading_goal":
            goal_id = request.POST.get("goal_id")
            deleted, _ = ReadingGoal.objects.filter(pk=goal_id).delete()
            if deleted:
                messages.success(request, "Reading goal deleted.")
            return redirect("web:settings")

        return redirect("web:settings")


@login_required
def web_export_json(request):
    data = export_json()
    response = HttpResponse(
        json.dumps(data, indent=2),
        content_type="application/json",
    )
    response["Content-Disposition"] = 'attachment; filename="openbook-export.json"'
    return response


@login_required
def web_export_csv(request):
    csv_data = export_csv()
    response = HttpResponse(csv_data, content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="openbook-export.csv"'
    return response


class StatsPageView(LoginRequiredMixin, TemplateView):
    template_name = "stats/stats.html"

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["stats/partials/year_scope.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        period_start, period_end, period_label = parse_stats_period(
            self.request.GET.get("period"),
            self.request.GET.get("start"),
            self.request.GET.get("end"),
        )
        stats = compute_stats(period_start, period_end)
        ctx["stats"] = stats
        ctx["stats_period"] = self.request.GET.get("period") or "all"
        ctx["stats_period_label"] = period_label
        ctx["stats_period_start"] = period_start.isoformat() if period_start else ""
        ctx["stats_period_end"] = period_end.isoformat() if period_end else ""
        ctx["metrics_items"] = [
            {"value": stats["total_books"], "label": "Total Books"},
            {"value": int(round(stats["completion_rate"] * 100)), "suffix": "%", "label": "Completion Rate"},
            {"value": stats["reading_streak"], "label": "Day Streak"},
            {"value": stats["pages_read"], "label": "Pages Read"},
        ]

        selected_year, selected_month = parse_stats_year_month(
            self.request.GET.get("year"),
            self.request.GET.get("month"),
        )
        available_years = stats_available_years()
        monthly_reads = monthly_reads_for_year(selected_year)
        pages_per_month = pages_per_month_for_year(selected_year)
        finish_calendar_strip_data = finish_calendar_strip(selected_year, selected_month)
        finish_calendars = finish_calendar_strip_data["calendars"]

        status_labels = dict(ReadingStatus.choices)
        books_by_status = [
            {"status": status_labels.get(row["status"], row["status"]), "count": row["count"]}
            for row in stats["books_by_status"]
        ]

        ctx["selected_year"] = selected_year
        ctx["selected_month"] = selected_month
        ctx["available_years"] = available_years
        ctx["yearly_monthly_reads"] = monthly_reads
        ctx["finish_calendars"] = finish_calendars
        ctx["calendar_range_label"] = finish_calendar_strip_data["range_label"]
        ctx["stats_json_shelf"] = json.dumps(stats["books_by_shelf"])
        ctx["stats_json_genre"] = json.dumps(stats["books_by_genre"])
        ctx["stats_json_monthly"] = json.dumps(monthly_reads)
        ctx["stats_json_status"] = json.dumps(books_by_status)
        ctx["stats_json_pages_month"] = json.dumps(pages_per_month)
        ctx["stats_json_heatmap"] = json.dumps(stats.get("reading_heatmap", []))
        ctx["stats_json_rating"] = json.dumps(stats.get("rating_distribution", []))
        ctx["stats_json_format"] = json.dumps(stats.get("format_breakdown", []))
        ctx["stats_dnf"] = stats.get("dnf_stats", {})
        ctx["stats_reading_speed"] = stats.get("reading_speed", {})

        prev_month = selected_month - 1 if selected_month > 1 else None
        next_month = selected_month + 1
        today = timezone.localdate()
        if selected_year == today.year and next_month > today.month:
            next_month = None

        ctx["calendar_prev_url"] = (
            reverse("web:stats") + f"?year={selected_year}&month={prev_month}" if prev_month else None
        )
        ctx["calendar_next_url"] = (
            reverse("web:stats") + f"?year={selected_year}&month={next_month}" if next_month else None
        )
        return ctx

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        if self.request.headers.get("HX-Request") and context.get("stats", {}).get("total_books"):
            response["HX-Trigger"] = json.dumps(
                {
                    "statsYearUpdated": {
                        "monthly": context["yearly_monthly_reads"],
                        "pages": json.loads(context["stats_json_pages_month"]),
                    }
                }
            )
        return response


class FinishedOnDayView(LoginRequiredMixin, View):
    def get(self, request, year: int, month: int, day: int):
        try:
            target_date = date(year, month, day)
        except ValueError:
            return HttpResponse(status=404)
        books = books_finished_on(target_date)
        return render(
            request,
            "stats/partials/finished_on_day.html",
            {
                "target_date": target_date,
                "books": books,
            },
        )


class YearReviewView(LoginRequiredMixin, TemplateView):
    template_name = "stats/year_review.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        year = int(self.kwargs["year"])
        ctx["year"] = year
        review = compute_year_review(year)
        ctx["review"] = review
        ctx["metrics_items"] = [
            {"value": review["books_finished"], "label": "Books Finished"},
            {"value": review["pages_read"], "label": "Pages Read"},
            {"value": review["average_rating"] or "—", "label": "Avg Rating"},
            {"value": review["longest_streak"], "label": "Day Streak"},
        ]
        return ctx


class ImportExportView(LoginRequiredMixin, TemplateView):
    template_name = "import_export/import_export.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["isbn_form"] = ISBNImportForm()
        ctx["csv_form"] = CSVImportForm()
        ctx["recent_jobs"] = ImportJob.objects.filter(user=self.request.user)[:5]
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        if action == "import_isbns":
            form = ISBNImportForm(request.POST)
            if form.is_valid():
                lines = [line.strip() for line in form.cleaned_data["isbns"].splitlines() if line.strip()]
                job = create_isbn_job(request.user, lines)
                messages.info(request, "Import queued. Processing in the background.")
                return redirect("web:import-job-detail", pk=job.pk)
            messages.error(request, "Please enter at least one ISBN.")
            return redirect("web:import-export")

        if action == "preview_csv":
            form = CSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                job = create_csv_preview_job(request.user, form.cleaned_data["csv_file"])
                messages.info(request, "Preview ready. Confirm import on the job page.")
                return redirect("web:import-job-detail", pk=job.pk)
            messages.error(request, "Please upload a valid CSV file.")
            return redirect("web:import-export")

        if action == "export_json":
            data = export_json()
            response = HttpResponse(
                json.dumps(data, indent=2),
                content_type="application/json",
            )
            response["Content-Disposition"] = 'attachment; filename="openbook-export.json"'
            return response

        if action == "export_csv":
            csv_data = export_csv()
            response = HttpResponse(csv_data, content_type="text/csv")
            response["Content-Disposition"] = 'attachment; filename="openbook-export.csv"'
            return response

        return redirect("web:import-export")


class ImportJobDetailView(LoginRequiredMixin, TemplateView):
    template_name = "import_export/import_job_detail.html"

    def get_job(self):
        return get_object_or_404(ImportJob, pk=self.kwargs["pk"], user=self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        job = self.get_job()
        ctx["job"] = job
        if job.kind == ImportJobKind.METADATA_BACKFILL:
            ctx["back_url"] = reverse("web:library-tools")
            ctx["back_label"] = "Library Tools"
        else:
            ctx["back_url"] = reverse("web:import-export")
            ctx["back_label"] = "Import / Export"
        return ctx

    def post(self, request, *args, **kwargs):
        job = self.get_job()
        if request.POST.get("action") == "confirm_csv":
            if job.status == ImportJobStatus.AWAITING_CONFIRMATION:
                confirm_csv_job(job)
                messages.info(request, "Import queued. Processing in the background.")
            else:
                messages.warning(request, "This import cannot be confirmed.")
        elif request.POST.get("action") == "process_now":
            if job.status in (ImportJobStatus.PENDING, ImportJobStatus.RUNNING):
                schedule_import_processing(force=True)
                messages.info(request, "Import worker triggered.")
        elif request.POST.get("action") == "cancel":
            try:
                was_pending = job.status == ImportJobStatus.PENDING
                request_cancel_import_job(job)
                if was_pending:
                    messages.info(request, "Job cancelled.")
                else:
                    messages.info(request, "Cancellation requested. The job will stop after the current item.")
            except ValueError as exc:
                messages.warning(request, str(exc))
        next_url = request.POST.get("next")
        if next_url:
            return redirect(next_url)
        return redirect("web:import-job-detail", pk=job.pk)


class ImportJobStatusPartialView(LoginRequiredMixin, View):
    def get(self, request, pk):
        job = get_object_or_404(ImportJob, pk=pk, user=request.user)
        return render(
            request,
            "import_export/partials/job_status.html",
            {"job": job, "cancel_next": request.GET.get("next", "")},
        )


class ImportJobProcessView(LoginRequiredMixin, View):
    def post(self, request, pk):
        get_object_or_404(ImportJob, pk=pk, user=request.user)
        schedule_import_processing(force=True)
        return HttpResponse(status=204)


class LibraryToolsView(LoginRequiredMixin, TemplateView):
    template_name = "library_tools/library_tools.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["health"] = library_health_stats()
        ctx["needing_metadata_count"] = ctx["health"]["needing_metadata"]
        ctx["pending_matches"] = MetadataMatchProposal.objects.filter(
            status=MetadataMatchProposalStatus.PENDING,
        ).select_related("book").prefetch_related("book__authors")
        ctx["recent_jobs"] = ImportJob.objects.filter(
            user=self.request.user,
            kind=ImportJobKind.METADATA_BACKFILL,
        )[:5]
        ctx["active_backfill_job"] = ImportJob.objects.filter(
            user=self.request.user,
            kind=ImportJobKind.METADATA_BACKFILL,
            status__in=(ImportJobStatus.PENDING, ImportJobStatus.RUNNING),
        ).first()
        from django.db.models import Count

        ctx["genres_for_manage"] = Genre.objects.annotate(book_count=Count("book_genres")).order_by("name")[:20]
        ctx["duplicate_groups"] = find_duplicate_groups()
        ctx["duplicate_author_groups"] = find_duplicate_author_groups()
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        if action == "backfill_metadata":
            active = ImportJob.objects.filter(
                user=request.user,
                kind=ImportJobKind.METADATA_BACKFILL,
                status__in=(ImportJobStatus.PENDING, ImportJobStatus.RUNNING),
            ).first()
            if active:
                messages.warning(request, "A metadata backfill is already in progress.")
                return redirect("web:import-job-detail", pk=active.pk)
            book_ids = [str(pk) for pk in books_needing_metadata().values_list("pk", flat=True)]
            if not book_ids:
                messages.info(request, "No books need metadata backfill.")
                return redirect("web:library-tools")
            job = create_metadata_backfill_job(request.user, book_ids)
            messages.info(request, "Metadata backfill queued. Processing in the background.")
            return redirect("web:import-job-detail", pk=job.pk)

        if action == "resolve_high_confidence":
            resolved = 0
            for proposal in MetadataMatchProposal.objects.filter(
                status=MetadataMatchProposalStatus.PENDING,
            ).select_related("book"):
                lookup = lookup_for_book(proposal.book, import_context=True)
                if lookup.auto_apply:
                    apply_lookup_result(proposal.book, lookup, mode="fill")
                    proposal.status = MetadataMatchProposalStatus.APPLIED
                    proposal.save(update_fields=["status", "updated_at"])
                    resolved += 1
            if resolved:
                messages.success(request, f"Applied metadata to {resolved} book(s).")
            else:
                messages.info(request, "No pending matches met the auto-apply threshold.")
            return redirect("web:library-tools")

        if action == "clear_metadata_cache":
            deleted = clear_metadata_cache()
            if deleted:
                messages.success(request, f"Cleared {deleted} cached metadata entries.")
            else:
                messages.success(request, "Metadata cache cleared.")
            return redirect("web:library-tools")

        if action == "merge_duplicates":
            keeper_id = request.POST.get("keeper_id")
            group_book_ids = request.POST.getlist("group_book_ids")
            merge_ids = [book_id for book_id in group_book_ids if book_id != keeper_id]
            if not keeper_id or not merge_ids:
                messages.error(request, "Select a book to keep and at least one duplicate to merge.")
                return redirect("web:library-tools")
            try:
                keeper = merge_books(keeper_id, merge_ids)
            except Book.DoesNotExist:
                messages.error(request, "One or more books could not be found.")
                return redirect("web:library-tools")
            messages.success(request, f'Merged duplicates into "{keeper.title}".')
            return redirect("web:library-tools")

        if action == "merge_authors":
            primary_id = request.POST.get("primary_author_id")
            author_ids = [int(x) for x in request.POST.getlist("author_ids") if x.isdigit()]
            duplicate_ids = [aid for aid in author_ids if str(aid) != str(primary_id)]
            if not primary_id or not duplicate_ids:
                messages.error(request, "Select a primary author and duplicates to merge.")
                return redirect("web:library-tools")
            primary = get_object_or_404(Author, pk=primary_id)
            merge_authors(primary, duplicate_ids)
            messages.success(request, f'Merged authors into "{primary.name}".')
            return redirect("web:library-tools")

        if action == "backfill_missing_covers":
            book_ids = [
                str(pk)
                for pk in apply_health_missing_filter(Book.objects.all(), "cover").values_list("pk", flat=True)
            ]
            if not book_ids:
                messages.info(request, "No books missing covers.")
                return redirect("web:library-tools")
            job = create_metadata_backfill_job(request.user, book_ids)
            messages.info(request, "Cover backfill queued.")
            return redirect("web:import-job-detail", pk=job.pk)

        return redirect("web:library-tools")


@login_required
def metadata_match_apply(request, pk):
    proposal = get_object_or_404(
        MetadataMatchProposal,
        pk=pk,
        status=MetadataMatchProposalStatus.PENDING,
    )
    if request.method != "POST":
        return redirect("web:library-tools")

    result = LookupResult(
        metadata=proposal.candidate,
        score=proposal.score,
        auto_apply=True,
    )
    apply_lookup_result(proposal.book, result, mode="fill")
    proposal.status = MetadataMatchProposalStatus.APPLIED
    proposal.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Applied metadata to “{proposal.book.title}”.")
    return redirect("web:library-tools")


@login_required
def metadata_match_reject(request, pk):
    proposal = get_object_or_404(
        MetadataMatchProposal,
        pk=pk,
        status=MetadataMatchProposalStatus.PENDING,
    )
    if request.method == "POST":
        proposal.status = MetadataMatchProposalStatus.REJECTED
        proposal.save(update_fields=["status", "updated_at"])
        messages.info(request, f"Rejected metadata match for “{proposal.book.title}”.")
    return redirect("web:library-tools")


@login_required
def metadata_match_apply_alternate(request, pk):
    proposal = get_object_or_404(
        MetadataMatchProposal,
        pk=pk,
        status=MetadataMatchProposalStatus.PENDING,
    )
    if request.method != "POST":
        return redirect("web:library-tools")

    try:
        alt_index = int(request.POST.get("alternate_index", 0))
    except (TypeError, ValueError):
        alt_index = 0

    alternates = proposal.alternates or []
    if alt_index < 0 or alt_index >= len(alternates):
        messages.warning(request, "Invalid alternate selection.")
        return redirect("web:library-tools")

    result = LookupResult(metadata=alternates[alt_index], score=proposal.score, auto_apply=True)
    apply_lookup_result(proposal.book, result, mode="fill")
    proposal.status = MetadataMatchProposalStatus.APPLIED
    proposal.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Applied alternate metadata to “{proposal.book.title}”.")
    return redirect("web:library-tools")


@login_required
def book_refresh_metadata(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method != "POST":
        return redirect("web:book-detail", pk=pk)

    if not (book.title or "").strip():
        messages.warning(request, "Need a title to look up metadata.")
        return redirect("web:book-detail", pk=pk)

    result = refresh_book_metadata(book)
    if result.updated_fields:
        labels = ", ".join(result.updated_fields)
        messages.success(request, f"Updated: {labels}.")
    else:
        messages.info(request, "No new metadata found.")

    return redirect("web:book-detail", pk=pk)


def embed_widget(request):
    from accounts.models import UserProfile
    from books.embed import embed_payload

    key = request.GET.get("key", "").strip()
    kind = request.GET.get("kind", "currently_reading")
    profile = UserProfile.objects.filter(embed_enabled=True, embed_key=key).first()
    if not profile:
        return HttpResponse("// openbook embed: invalid key", content_type="application/javascript")

    payload = embed_payload(kind=kind if kind in ("currently_reading", "recently_finished") else "currently_reading")
    return render(
        request,
        "embed/widget.js",
        {"payload_json": json.dumps(payload)},
        content_type="application/javascript",
    )


def public_profile(request):
    from accounts.models import UserProfile
    from books.embed import profile_payload, profile_stats_summary
    from books.models import ReadingLog, ReadingStatus

    key = request.GET.get("key", "").strip()
    profile = UserProfile.objects.filter(embed_enabled=True, embed_key=key).select_related("user").first()
    if not profile:
        return render(request, "profile/forbidden.html", status=403)

    stats = profile_stats_summary()
    currently_reading = (
        ReadingLog.objects.filter(status=ReadingStatus.READING)
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("-updated_at")[:10]
    )
    recently_read = (
        ReadingLog.objects.filter(status=ReadingStatus.FINISHED, finished_at__isnull=False)
        .select_related("book")
        .prefetch_related("book__authors")
        .order_by("-finished_at")[:10]
    )

    display_name = profile.user.get_full_name() or profile.user.email.split("@")[0]
    metrics_items = [
        {"value": stats["total_books"], "label": "Total Books"},
        {"value": int(round(stats["completion_rate"] * 100)), "suffix": "%", "label": "Completion Rate"},
        {"value": stats["reading_streak"], "label": "Day Streak"},
        {"value": stats["pages_read"], "label": "Pages Read"},
    ]
    return render(
        request,
        "profile/public.html",
        {
            "display_name": display_name,
            "currently_reading": currently_reading,
            "recently_read": recently_read,
            "stats": stats,
            "metrics_items": metrics_items,
            "profile_json": json.dumps(profile_payload(request=request)),
        },
    )


@login_required
def book_metadata_locks(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        locked = [field for field in METADATA_LOCK_FIELDS if request.POST.get(f"lock_{field}") == "on"]
        book.metadata_locked_fields = locked
        book.save(update_fields=["metadata_locked_fields", "updated_at"])
        messages.success(request, "Metadata lock settings saved.")
    return redirect("web:book-detail", pk=pk)


@login_required
def book_tag_add(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        from django.utils.text import slugify

        name = (request.POST.get("tag_name") or "").strip()
        if name:
            slug = slugify(name)[:120] or "tag"
            tag, _ = BookTag.objects.get_or_create(name=name, defaults={"slug": slug})
            BookTaggedItem.objects.get_or_create(book=book, tag=tag)
            messages.success(request, f'Added tag "{name}".')
    return redirect("web:book-detail", pk=pk)


@login_required
def book_tag_remove(request, pk, tag_id):
    book = get_object_or_404(Book, pk=pk)
    if request.method == "POST":
        BookTaggedItem.objects.filter(book=book, tag_id=tag_id).delete()
        messages.success(request, "Tag removed.")
    return redirect("web:book-detail", pk=pk)
