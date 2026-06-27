import pytest
from django.urls import reverse

from accounts.factories import UserFactory
from books.factories import BookFactory


@pytest.fixture
def web_user(db):
    return UserFactory(email="web@example.com", password="password123")


@pytest.fixture
def logged_in_client(client, web_user):
    client.login(username="web@example.com", password="password123")
    return client


@pytest.mark.django_db
def test_login_page_loads(client, web_user):
    response = client.get(reverse("login"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get(reverse("web:dashboard"))
    assert response.status_code == 302
    assert response.url == reverse("setup")


@pytest.mark.django_db
def test_dashboard_loads(logged_in_client):
    response = logged_in_client.get(reverse("web:dashboard"))
    assert response.status_code == 200
    assert b"Dashboard" in response.content
    assert b'name="search"' in response.content
    assert b"nav-item-active" in response.content


@pytest.mark.django_db
def test_dashboard_shows_reading_progress_bar(logged_in_client):
    from books.models import ReadingStatus

    book = BookFactory(title="In Progress")
    log = book.reading_log
    log.status = ReadingStatus.READING
    log.progress_percent = 45
    log.save()
    response = logged_in_client.get(reverse("web:dashboard"))
    assert response.status_code == 200
    assert b'role="progressbar"' in response.content
    assert b"45% done" in response.content


@pytest.mark.django_db
def test_book_list_loads(logged_in_client):
    BookFactory(title="Test Book")
    response = logged_in_client.get(reverse("web:book-list"))
    assert response.status_code == 200
    assert b"Test Book" in response.content
    assert b"book-list-loading" in response.content
    assert b"skeleton" in response.content


@pytest.mark.django_db
def test_book_add(logged_in_client):
    response = logged_in_client.post(
        reverse("web:book-add"),
        {
            "title": "New Book",
            "author_names": "Jane Doe",
            "language": "en",
        },
    )
    assert response.status_code == 302
    assert response.url.startswith("/books/")


@pytest.mark.django_db
def test_healthz(client):
    response = client.get(reverse("healthz"))
    assert response.status_code == 200
    assert response.json()["database"] is True


@pytest.mark.django_db
def test_stats_page(logged_in_client):
    response = logged_in_client.get(reverse("web:stats"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_import_export_page(logged_in_client):
    response = logged_in_client.get(reverse("web:import-export"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_web_isbn_import_queues_job(logged_in_client, web_user):
    from books.models import ImportJob

    response = logged_in_client.post(
        reverse("web:import-export"),
        {"action": "import_isbns", "isbns": "9780143127555"},
    )
    assert response.status_code == 302
    job = ImportJob.objects.get(user=web_user)
    assert response.url == reverse("web:import-job-detail", kwargs={"pk": job.pk})


@pytest.mark.django_db
def test_web_csv_confirm_without_reupload(logged_in_client, web_user):
    import csv
    import io

    from books.import_jobs import create_csv_preview_job
    from books.models import ImportJobStatus

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Author", "ISBN", "ISBN13", "My Rating", "My Review",
        "Number of Pages", "Year Published", "Publisher", "Exclusive Shelf", "Bookshelves",
    ])
    writer.writerow([
        "Web CSV Book", "Author", "", '="9780143127556"', "0", "",
        "100", "2019", "Pub", "read", "",
    ])
    uploaded = io.BytesIO(output.getvalue().encode("utf-8"))
    uploaded.name = "goodreads.csv"

    job = create_csv_preview_job(web_user, uploaded)
    response = logged_in_client.post(
        reverse("web:import-job-detail", kwargs={"pk": job.pk}),
        {"action": "confirm_csv"},
    )
    assert response.status_code == 302
    job.refresh_from_db()
    assert job.status == ImportJobStatus.PENDING


@pytest.mark.django_db
def test_job_detail_pending_shows_process_now_and_cancel(logged_in_client, web_user):
    from books.import_jobs import create_metadata_backfill_job
    from books.models import ImportJobStatus

    book = BookFactory()
    job = create_metadata_backfill_job(web_user, [str(book.pk)])
    response = logged_in_client.get(reverse("web:import-job-detail", kwargs={"pk": job.pk}))
    assert response.status_code == 200
    content = response.content
    assert b"Process now" in content
    assert b"Cancel" in content
    assert job.status == ImportJobStatus.PENDING


@pytest.mark.django_db
def test_job_detail_running_shows_cancel_not_process_now(logged_in_client, web_user):
    from books.import_jobs import create_metadata_backfill_job
    from books.models import ImportJobStatus

    book = BookFactory()
    job = create_metadata_backfill_job(web_user, [str(book.pk)])
    job.status = ImportJobStatus.RUNNING
    job.save(update_fields=["status"])
    response = logged_in_client.get(reverse("web:import-job-detail", kwargs={"pk": job.pk}))
    assert response.status_code == 200
    content = response.content
    assert b"Process now" not in content
    assert b"Cancel" in content
    assert b"Running" in content


@pytest.mark.django_db
def test_web_cancel_import_job_redirects(logged_in_client, web_user):
    from books.import_jobs import create_metadata_backfill_job
    from books.models import ImportJobStatus

    book = BookFactory()
    job = create_metadata_backfill_job(web_user, [str(book.pk)])
    response = logged_in_client.post(
        reverse("web:import-job-detail", kwargs={"pk": job.pk}),
        {"action": "cancel"},
    )
    assert response.status_code == 302
    job.refresh_from_db()
    assert job.status == ImportJobStatus.CANCELLED


@pytest.mark.django_db
def test_shelves_page(logged_in_client):
    response = logged_in_client.get(reverse("web:shelf-list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_settings_page(logged_in_client):
    response = logged_in_client.get(reverse("web:settings"))
    assert response.status_code == 200
    assert b"API Tokens" in response.content
    assert b"Preferences" in response.content
    assert b"data-theme-option" in response.content
    assert b"books/theme.js" in response.content
    assert b"Save profile" in response.content
    assert b"Change password" in response.content
    assert b"Metadata providers" in response.content
    assert b"Lookup strategy" in response.content


@pytest.mark.django_db
def test_settings_change_password(client, web_user):
    web_user.set_password("oldpass123")
    web_user.save()
    client.login(username="web@example.com", password="oldpass123")
    response = client.post(
        reverse("web:settings"),
        {
            "action": "change_password",
            "old_password": "oldpass123",
            "new_password1": "newpass45678",
            "new_password2": "newpass45678",
        },
    )
    assert response.status_code == 302
    web_user.refresh_from_db()
    assert web_user.check_password("newpass45678")


@pytest.mark.django_db
def test_settings_profile_update(logged_in_client, web_user):
    from accounts.models import UserProfile

    UserProfile.objects.get_or_create(user=web_user)
    response = logged_in_client.post(
        reverse("web:settings"),
        {
            "action": "update_profile",
            "first_name": "Jane",
            "last_name": "Reader",
            "timezone": "America/New_York",
        },
    )
    assert response.status_code == 302
    web_user.refresh_from_db()
    assert web_user.first_name == "Jane"
    assert web_user.profile.timezone == "America/New_York"


@pytest.mark.django_db
def test_reading_log_page(logged_in_client):
    from books.models import ReadingStatus

    book = BookFactory(title="Reading Now")
    log = book.reading_log
    log.status = ReadingStatus.READING
    log.progress_percent = 50
    log.save()
    response = logged_in_client.get(reverse("web:reading-log"))
    assert response.status_code == 200
    assert b"Reading Log" in response.content
    assert b"Reading Now" in response.content


@pytest.mark.django_db
def test_genre_list_page(logged_in_client):
    from books.factories import GenreFactory

    GenreFactory(name="Fantasy")
    response = logged_in_client.get(reverse("web:genre-list"))
    assert response.status_code == 200
    assert b"Fantasy" in response.content


@pytest.mark.django_db
def test_header_search_partial(logged_in_client):
    BookFactory(title="Unique Searchable Title XYZ")
    response = logged_in_client.get(reverse("web:header-search"), {"search": "Unique Searchable"})
    assert response.status_code == 200
    assert b"Unique Searchable Title XYZ" in response.content


@pytest.mark.django_db
def test_book_list_sort_by_title(logged_in_client):
    BookFactory(title="Zebra Book")
    BookFactory(title="Alpha Book")
    response = logged_in_client.get(reverse("web:book-list"), {"sort": "title"})
    assert response.status_code == 200
    content = response.content.decode()
    assert content.index("Alpha Book") < content.index("Zebra Book")


@pytest.mark.django_db
def test_skip_link_present(logged_in_client):
    response = logged_in_client.get(reverse("web:dashboard"))
    assert b"Skip to main content" in response.content
    assert b'id="main-content"' in response.content


@pytest.mark.django_db
def test_book_detail_hero_shows_reading_status_summary(logged_in_client):
    from books.models import ReadingLog, ReadingStatus

    book = BookFactory(title="Status Hero Book", pages=350)
    log = ReadingLog.objects.get(book=book)
    log.status = ReadingStatus.READING
    log.progress_percent = 45
    log.current_page = 158
    log.save()

    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Currently Reading" in content
    assert "45%" in content
    assert "page 158 of 350" in content


@pytest.mark.django_db
def test_book_detail_book_details_accordion_contains_isbn(logged_in_client):
    book = BookFactory(isbn_13="9780143127550")
    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Book details" in content
    assert "9780143127550" in content
    assert "ISBN-13" in content


@pytest.mark.django_db
def test_book_detail_log_progress_disclosure_markup(logged_in_client):
    book = BookFactory()
    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    content = response.content.decode()
    assert 'id="reading-progress-details"' in content
    assert "group-open:rotate-180" in content
    assert "Log progress" in content


@pytest.mark.django_db
def test_book_detail_save_progress_inside_details(logged_in_client):
    book = BookFactory()
    response = logged_in_client.get(reverse("web:book-detail", kwargs={"pk": book.pk}))
    content = response.content.decode()
    summary_pos = content.index("Log progress")
    save_pos = content.index("Save progress")
    details_close_pos = content.index("</details>", summary_pos)
    assert summary_pos < save_pos < details_close_pos


@pytest.mark.django_db
def test_book_reading_status_change_via_htmx(logged_in_client):
    from books.models import ReadingLog, ReadingStatus

    book = BookFactory()
    log = ReadingLog.objects.get(book=book)
    assert log.status == ReadingStatus.NOT_STARTED

    response = logged_in_client.post(
        reverse("web:book-reading", kwargs={"pk": book.pk}),
        {"status": ReadingStatus.READING},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    log.refresh_from_db()
    assert log.status == ReadingStatus.READING


@pytest.mark.django_db
def test_book_edit_post_with_isbn(logged_in_client):
    book = BookFactory(title="Editable Book", isbn_13=None, isbn_10=None)
    response = logged_in_client.post(
        reverse("web:book-edit", kwargs={"pk": book.pk}),
        {
            "title": "Editable Book",
            "isbn": "9780143127550",
            "author_names": "",
            "format": "physical",
            "language": "en",
        },
    )
    assert response.status_code == 302
    book.refresh_from_db()
    assert book.isbn_13 == "9780143127550"


@pytest.mark.django_db
def test_book_list_grid_view(logged_in_client):
    BookFactory(title="Grid Book")
    response = logged_in_client.get(reverse("web:book-list"), {"view": "grid"})
    assert response.status_code == 200
    assert b"Grid Book" in response.content
    assert b"grid-cols-2" in response.content
    assert b"data-book-view-option" in response.content


@pytest.mark.django_db
def test_book_list_compact_view(logged_in_client):
    BookFactory(title="Compact Book")
    response = logged_in_client.get(reverse("web:book-list"), {"view": "compact"})
    assert response.status_code == 200
    assert b"Compact Book" in response.content
    assert b"surface-list" in response.content


@pytest.mark.django_db
def test_book_list_invalid_view_falls_back_to_list(logged_in_client):
    BookFactory(title="Fallback Book")
    response = logged_in_client.get(reverse("web:book-list"), {"view": "table"})
    assert response.status_code == 200
    assert b"Fallback Book" in response.content
    assert b"xl:grid-cols-5" not in response.content


@pytest.mark.django_db
def test_book_list_htmx_grid_partial(logged_in_client):
    BookFactory(title="HTMX Grid Book")
    response = logged_in_client.get(
        reverse("web:book-list"),
        {"view": "grid"},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 200
    assert b"HTMX Grid Book" in response.content
    assert b"grid-cols-2" in response.content
    assert b"page-title" not in response.content


@pytest.mark.django_db
def test_book_list_pagination_preserves_view_and_series(logged_in_client):
    from books.factories import SeriesFactory

    series = SeriesFactory(name="Pagination Series", slug="pagination-series")
    for i in range(25):
        BookFactory(title=f"Paged Book {i}", series=series)
    response = logged_in_client.get(
        reverse("web:book-list"),
        {"series": series.slug, "view": "grid", "page": 2},
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "view=grid" in content
    assert "series=pagination-series" in content


@pytest.mark.django_db
def test_book_list_collapsible_filter_controls(logged_in_client):
    response = logged_in_client.get(reverse("web:book-list"))
    assert response.status_code == 200
    assert b'id="book-filter-toggle"' in response.content
    assert b'id="book-filter-panel"' in response.content
    assert b"Search &amp; filters" in response.content
    assert b'id="book-filter-panel" class="mb-4 hidden"' in response.content


@pytest.mark.django_db
def test_book_list_filter_panel_open_when_filters_active(logged_in_client):
    from books.models import ReadingStatus

    response = logged_in_client.get(reverse("web:book-list"), {"status": ReadingStatus.READING})
    assert response.status_code == 200
    assert b'data-initial-open="true"' in response.content
    assert b"1 active" in response.content
    assert b"Clear filters" in response.content
    assert b'id="book-filter-panel" class="mb-4 "' in response.content
