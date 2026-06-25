import pytest
from django.db import IntegrityError

from accounts.factories import UserFactory
from books.factories import (
    BookAuthorFactory,
    BookFactory,
    BookshelfItemFactory,
    GenreFactory,
    ReviewFactory,
    ShelfFactory,
)
from books.models import Book, ReadingLog, ReadingStatus


@pytest.mark.django_db
class TestUserModel:
    def test_email_is_unique(self):
        UserFactory(email="test@example.com")
        with pytest.raises(IntegrityError):
            UserFactory(email="test@example.com")

    def test_username_field_is_email(self):
        user = UserFactory(email="reader@example.com")
        assert user.USERNAME_FIELD == "email"


@pytest.mark.django_db
class TestBookModel:
    def test_soft_delete_excludes_from_default_manager(self):
        book = BookFactory()
        book.deleted_at = book.updated_at
        book.save(update_fields=["deleted_at"])
        assert Book.objects.filter(pk=book.pk).count() == 0
        assert Book.all_objects.filter(pk=book.pk).count() == 1

    def test_isbn_13_unique(self):
        BookFactory(isbn_13="9780000000000")
        with pytest.raises(IntegrityError):
            BookFactory(isbn_13="9780000000000")


@pytest.mark.django_db
class TestReviewModel:
    def test_one_review_per_book(self):
        book = BookFactory()
        ReviewFactory(book=book)
        with pytest.raises(IntegrityError):
            ReviewFactory(book=book)


@pytest.mark.django_db
class TestReadingLogModel:
    def test_one_reading_log_per_book(self):
        book = BookFactory()
        assert ReadingLog.objects.filter(book=book).count() == 1
        with pytest.raises(IntegrityError):
            ReadingLog.objects.create(book=book, status=ReadingStatus.NOT_STARTED)

    def test_default_status_is_not_started(self):
        book = BookFactory()
        log = book.reading_log
        assert log.status == ReadingStatus.NOT_STARTED


@pytest.mark.django_db
class TestShelfModel:
    def test_shelf_name_unique(self):
        ShelfFactory(name="Favourites")
        with pytest.raises(IntegrityError):
            ShelfFactory(name="Favourites")

    def test_book_on_shelf_once(self):
        item = BookshelfItemFactory()
        with pytest.raises(IntegrityError):
            BookshelfItemFactory(book=item.book, shelf=item.shelf)


@pytest.mark.django_db
class TestGenreModel:
    def test_genre_slug_unique(self):
        GenreFactory(slug="fiction")
        with pytest.raises(IntegrityError):
            GenreFactory(name="Other Fiction", slug="fiction")


@pytest.mark.django_db
class TestBookAuthorModel:
    def test_book_author_unique_per_role(self):
        link = BookAuthorFactory()
        with pytest.raises(IntegrityError):
            BookAuthorFactory(book=link.book, author=link.author, role=link.role)
