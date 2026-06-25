import pytest
from django.urls import reverse
from rest_framework import status

from books.factories import BookFactory, BookshelfItemFactory, ShelfFactory
from books.models import Book, BookshelfItem, Shelf


@pytest.mark.django_db
class TestShelfAPI:
    def test_list_shelves_requires_auth(self, api_client):
        response = api_client.get(reverse("shelf-list"))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_shelf(self, authenticated_client):
        response = authenticated_client.post(
            reverse("shelf-list"),
            {"name": "Favourites", "color": "#6366f1", "sort_order": 1},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["data"]["name"] == "Favourites"
        assert body["data"]["color"] == "#6366f1"
        assert body["data"]["book_count"] == 0
        assert Shelf.objects.filter(name="Favourites").exists()

    def test_retrieve_update_delete_shelf(self, authenticated_client):
        shelf = ShelfFactory(name="Sci-Fi TBR")

        detail = authenticated_client.get(reverse("shelf-detail", args=[shelf.pk]))
        assert detail.status_code == status.HTTP_200_OK
        assert detail.json()["data"]["name"] == "Sci-Fi TBR"

        updated = authenticated_client.patch(
            reverse("shelf-detail", args=[shelf.pk]),
            {"name": "Sci-Fi", "description": "To read"},
            format="json",
        )
        assert updated.status_code == status.HTTP_200_OK
        shelf.refresh_from_db()
        assert shelf.name == "Sci-Fi"
        assert shelf.description == "To read"

        deleted = authenticated_client.delete(reverse("shelf-detail", args=[shelf.pk]))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT
        assert not Shelf.objects.filter(pk=shelf.pk).exists()

    def test_shelf_delete_does_not_delete_books(self, authenticated_client):
        item = BookshelfItemFactory()
        shelf_id = item.shelf_id
        book_id = item.book_id

        response = authenticated_client.delete(reverse("shelf-detail", args=[shelf_id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not BookshelfItem.objects.filter(shelf_id=shelf_id).exists()
        assert Book.objects.filter(pk=book_id).exists()


@pytest.mark.django_db
class TestShelveAPI:
    def test_shelve_and_unshelve_book(self, authenticated_client):
        book = BookFactory()
        shelf = ShelfFactory()

        shelve = authenticated_client.post(
            reverse("book-shelve", args=[book.pk]),
            {"shelf_id": shelf.pk},
            format="json",
        )
        assert shelve.status_code == status.HTTP_200_OK
        assert shelve.json()["data"] == {
            "book_id": str(book.pk),
            "shelf_id": shelf.pk,
        }
        assert BookshelfItem.objects.filter(book=book, shelf=shelf).exists()

        duplicate = authenticated_client.post(
            reverse("book-shelve", args=[book.pk]),
            {"shelf_id": shelf.pk},
            format="json",
        )
        assert duplicate.status_code == status.HTTP_200_OK
        assert BookshelfItem.objects.filter(book=book, shelf=shelf).count() == 1

        unshelve = authenticated_client.post(
            reverse("book-unshelve", args=[book.pk]),
            {"shelf_id": shelf.pk},
            format="json",
        )
        assert unshelve.status_code == status.HTTP_200_OK
        assert not BookshelfItem.objects.filter(book=book, shelf=shelf).exists()

    def test_unshelve_missing_returns_404(self, authenticated_client):
        book = BookFactory()
        shelf = ShelfFactory()

        response = authenticated_client.post(
            reverse("book-unshelve", args=[book.pk]),
            {"shelf_id": shelf.pk},
            format="json",
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["error"]["code"] == "not_found"

    def test_shelve_requires_shelf_id(self, authenticated_client):
        book = BookFactory()

        response = authenticated_client.post(
            reverse("book-shelve", args=[book.pk]),
            {},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["code"] == "validation_error"
