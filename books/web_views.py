import json

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
from rest_framework.authtoken.models import Token

from accounts.forms import ProfileForm
from accounts.models import UserProfile
from books.covers import download_cover
from books.forms import (
    BookFilterForm,
    BookForm,
    CSVImportForm,
    ISBNImportForm,
    QuoteForm,
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
)
from books.import_worker import schedule_import_processing
from books.library_maintenance import (
    books_needing_metadata,
    clear_metadata_cache,
    library_health_stats,
    refresh_book_metadata,
)
from books.metadata import MetadataService
from books.models import (
    Author,
    Book,
    BookshelfItem,
    Genre,
    ImportJob,
    ImportJobKind,
    ImportJobStatus,
    Quote,
    ReadingLog,
    ReadingStatus,
    Review,
    Shelf,
    _IS_POSTGRESQL,
)
from books.provider_links import book_provider_links
from books.reading_timeline import build_reading_timeline
from books.reading_service import update_reading_log
from books.services import attach_authors_to_book, attach_genres_to_book, create_reading_log_for_book
from books.stats import compute_stats, genres_for_filter
from books.status_shelves import get_status_shelf, get_status_shelves


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
        return ctx


def _filter_books(request):
    qs = Book.objects.prefetch_related("authors", "genres").select_related("reading_log", "review")
    form = BookFilterForm(request.GET or None)
    search = request.GET.get("search", "").strip()
    shelf_id = request.GET.get("shelf")
    genre_id = request.GET.get("genre")
    status = request.GET.get("status")
    rating = request.GET.get("rating")
    sort = request.GET.get("sort", "-created_at")

    if search:
        if _IS_POSTGRESQL:
            from django.contrib.postgres.search import SearchQuery, SearchRank

            query = SearchQuery(search)
            qs = qs.filter(
                Q(search_vector=query)
                | Q(title__icontains=search)
                | Q(authors__name__icontains=search)
                | Q(isbn_13=search)
                | Q(isbn_10=search)
            ).annotate(rank=SearchRank("search_vector", query)).distinct()
            if sort == "-created_at":
                qs = qs.order_by("-rank", "-created_at")
            else:
                qs = _apply_book_sort(qs, sort)
        else:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(authors__name__icontains=search)
                | Q(isbn_13=search)
                | Q(isbn_10=search)
            ).distinct()
            qs = _apply_book_sort(qs, sort)
    else:
        qs = _apply_book_sort(qs, sort)

    if shelf_id:
        qs = qs.filter(bookshelf_items__shelf_id=shelf_id)
    if genre_id:
        qs = qs.filter(book_genres__genre_id=genre_id)
    if status:
        qs = qs.filter(reading_log__status=status)
    if rating:
        qs = qs.filter(review__rating=rating)

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


class BookListView(LoginRequiredMixin, ListView):
    template_name = "books/list.html"
    context_object_name = "books"
    paginate_by = 20

    def get_queryset(self):
        self.filter_form = BookFilterForm(self.request.GET or None)
        qs, _ = _filter_books(self.request)
        return qs

    def get_template_names(self):
        if self.request.headers.get("HX-Request"):
            return ["books/partials/book_rows.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        ctx["shelves"] = Shelf.objects.all()
        ctx["genres"] = genres_for_filter()
        ctx["reading_statuses"] = ReadingStatus.choices
        ctx["sort_choices"] = SORT_CHOICES
        return ctx


class BookDetailView(LoginRequiredMixin, DetailView):
    model = Book
    template_name = "books/detail.html"
    context_object_name = "book"

    def get_queryset(self):
        return Book.objects.prefetch_related("authors", "genres", "bookshelf_items__shelf").select_related(
            "reading_log", "review"
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
        else:
            ctx["reading_form"] = ReadingUpdateForm(initial={"status": ReadingStatus.NOT_STARTED})
        ctx["shelve_form"] = ShelveForm()
        ctx["all_shelves"] = Shelf.objects.all()
        ctx["book_shelves"] = Shelf.objects.filter(bookshelf_items__book=book)
        ctx["can_refresh_metadata"] = bool(book.isbn_13 or book.isbn_10)
        ctx["provider_links"] = book_provider_links(book)
        ctx["reading_timeline"] = build_reading_timeline(log)
        ctx["quote_form"] = QuoteForm()
        ctx["quotes"] = book.quotes.all()[:20]
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
        attach_authors_to_book(book, form.get_author_list())
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
        attach_authors_to_book(book, form.get_author_list())
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


class ShelfDetailView(LoginRequiredMixin, DetailView):
    model = Shelf
    template_name = "shelves/detail.html"
    context_object_name = "shelf"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["books"] = (
            Book.objects.filter(bookshelf_items__shelf=self.object)
            .prefetch_related("authors")
            .select_related("reading_log")
        )
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


class GenreDetailView(LoginRequiredMixin, DetailView):
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
        return ctx


class StatusShelfDetailView(LoginRequiredMixin, TemplateView):
    template_name = "shelves/status_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_shelf = get_status_shelf(self.kwargs["slug"])
        ctx["status_shelf"] = status_shelf
        ctx["books"] = (
            Book.objects.filter(reading_log__status=status_shelf.status)
            .prefetch_related("authors")
            .select_related("reading_log")
        )
        return ctx


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
            })},
        )
    return redirect("web:book-detail", pk=pk)


class TrashListView(LoginRequiredMixin, ListView):
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
        token, _ = Token.objects.get_or_create(user=self.request.user)
        ctx["api_token"] = token.key
        ctx["new_token"] = self.request.session.pop("new_token", None)
        ctx["embed_enabled"] = profile.embed_enabled
        ctx["embed_key"] = ensure_embed_key(profile) if profile.embed_enabled else profile.embed_key
        ctx["embed_base_url"] = self.request.build_absolute_uri("/")[:-1]
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "regenerate_token":
            Token.objects.filter(user=request.user).delete()
            token = Token.objects.create(user=request.user)
            request.session["new_token"] = token.key
            messages.success(request, "API token regenerated.")
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
        return redirect("web:settings")


class StatsPageView(LoginRequiredMixin, TemplateView):
    template_name = "stats/stats.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        stats = compute_stats()
        ctx["stats"] = stats
        ctx["metrics_items"] = [
            {"value": stats["total_books"], "label": "Total Books"},
            {"value": int(round(stats["completion_rate"] * 100)), "suffix": "%", "label": "Completion Rate"},
            {"value": stats["reading_streak"], "label": "Day Streak"},
            {"value": stats["pages_read"], "label": "Pages Read"},
        ]
        ctx["stats_json_shelf"] = json.dumps(stats["books_by_shelf"])
        ctx["stats_json_genre"] = json.dumps(stats["books_by_genre"])
        ctx["stats_json_monthly"] = json.dumps(stats["monthly_reads"])
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
        return redirect("web:import-job-detail", pk=job.pk)


class ImportJobStatusPartialView(LoginRequiredMixin, View):
    def get(self, request, pk):
        job = get_object_or_404(ImportJob, pk=pk, user=request.user)
        return render(
            request,
            "import_export/partials/job_status.html",
            {"job": job},
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
        ctx["recent_jobs"] = ImportJob.objects.filter(
            user=self.request.user,
            kind=ImportJobKind.METADATA_BACKFILL,
        )[:5]
        return ctx

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")

        if action == "backfill_metadata":
            book_ids = [str(pk) for pk in books_needing_metadata().values_list("pk", flat=True)]
            if not book_ids:
                messages.info(request, "No books need metadata backfill.")
                return redirect("web:library-tools")
            job = create_metadata_backfill_job(request.user, book_ids)
            messages.info(request, "Metadata backfill queued. Processing in the background.")
            return redirect("web:import-job-detail", pk=job.pk)

        if action == "clear_metadata_cache":
            deleted = clear_metadata_cache()
            if deleted:
                messages.success(request, f"Cleared {deleted} cached metadata entries.")
            else:
                messages.success(request, "Metadata cache cleared.")
            return redirect("web:library-tools")

        return redirect("web:library-tools")


@login_required
def book_refresh_metadata(request, pk):
    book = get_object_or_404(Book, pk=pk)
    if request.method != "POST":
        return redirect("web:book-detail", pk=pk)

    if not (book.isbn_13 or book.isbn_10):
        messages.warning(request, "No ISBN — cannot look up metadata.")
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
