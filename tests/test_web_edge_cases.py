import pytest
from django.urls import reverse

from accounts.factories import UserFactory
from books.factories import BookFactory


@pytest.fixture
def logged_in_client(client, db):
    UserFactory(email="edge@example.com", password="password123")
    client.login(username="edge@example.com", password="password123")
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    ["rating=abc", "rating=99999999999999999999", "series=99999999999999999999"],
)
def test_book_list_bad_filter_values_do_not_500(logged_in_client, query):
    BookFactory()
    response = logged_in_client.get(reverse("web:book-list") + "?" + query)
    assert response.status_code == 200
    assert list(response.context["books"]) == []


@pytest.mark.django_db
def test_book_list_numeric_rating_still_filters(logged_in_client):
    BookFactory()
    response = logged_in_client.get(reverse("web:book-list") + "?rating=5")
    assert response.status_code == 200


@pytest.mark.django_db
def test_finished_on_huge_year_is_404(logged_in_client):
    url = reverse(
        "web:stats-finished-on",
        kwargs={"year": 99999999999999999999, "month": 1, "day": 1},
    )
    assert logged_in_client.get(url).status_code == 404
