import pytest
from django.urls import reverse

from accounts.factories import UserFactory
from books.factories import ShelfFactory


@pytest.fixture
def logged_in_client(client, db):
    user = UserFactory(email="batch8@example.com", password="password123")
    client.login(username=user.email, password="password123")
    return client


@pytest.mark.django_db
def test_shelf_reorder_updates_sort_order(logged_in_client):
    first = ShelfFactory(name="Alpha", sort_order=0)
    second = ShelfFactory(name="Beta", sort_order=1)
    third = ShelfFactory(name="Gamma", sort_order=2)

    response = logged_in_client.post(
        reverse("web:shelf-reorder"),
        {"shelf_ids": [str(third.pk), str(first.pk), str(second.pk)]},
        HTTP_HX_REQUEST="true",
    )
    assert response.status_code == 204

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()
    assert third.sort_order == 0
    assert first.sort_order == 1
    assert second.sort_order == 2


@pytest.mark.django_db
def test_shelves_page_includes_sortable_assets(logged_in_client):
    ShelfFactory(name="Reorderable")
    response = logged_in_client.get(reverse("web:shelf-list"))
    assert response.status_code == 200
    assert b"sortablejs" in response.content.lower()
    assert b"custom-shelves-list" in response.content
    assert b"Drag to reorder" in response.content


@pytest.mark.django_db
def test_toast_shown_for_flash_message(logged_in_client):
    logged_in_client.post(
        reverse("web:shelf-list"),
        {"name": "Toast Shelf", "sort_order": 0},
        follow=False,
    )
    response = logged_in_client.get(reverse("web:shelf-list"))
    assert response.status_code == 200
    assert b'id="toast-stack"' in response.content
    assert b'aria-live="polite"' in response.content
    assert b"Shelf created." in response.content
