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
def test_shelves_page(logged_in_client):
    response = logged_in_client.get(reverse("web:shelf-list"))
    assert response.status_code == 200


@pytest.mark.django_db
def test_settings_page(logged_in_client):
    response = logged_in_client.get(reverse("web:settings"))
    assert response.status_code == 200
    assert b"API Token" in response.content
    assert b"Preferences" in response.content
    assert b"data-theme-option" in response.content
    assert b"books/theme.js" in response.content
    assert b"Save profile" in response.content
    assert b"id_timezone" in response.content


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
