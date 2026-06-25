import factory

from books.models import (
    Author,
    Book,
    BookAuthor,
    BookGenre,
    BookshelfItem,
    Genre,
    ReadingLog,
    ReadingProgress,
    ReadingStatus,
    Review,
    Shelf,
)


class AuthorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Author

    name = factory.Faker("name")


class BookFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Book

    title = factory.Faker("sentence", nb_words=4)
    language = "en"


class BookAuthorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BookAuthor

    book = factory.SubFactory(BookFactory)
    author = factory.SubFactory(AuthorFactory)
    position = 1


class GenreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Genre

    name = factory.Sequence(lambda n: f"Genre {n}")
    slug = factory.Sequence(lambda n: f"genre-{n}")


class ShelfFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Shelf

    name = factory.Sequence(lambda n: f"Shelf {n}")


class BookshelfItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BookshelfItem

    book = factory.SubFactory(BookFactory)
    shelf = factory.SubFactory(ShelfFactory)


class ReviewFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Review

    book = factory.SubFactory(BookFactory)
    rating = 4


class BookGenreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BookGenre

    book = factory.SubFactory(BookFactory)
    genre = factory.SubFactory(GenreFactory)


class ReadingLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReadingLog
        django_get_or_create = ("book",)

    book = factory.SubFactory(BookFactory)
    status = ReadingStatus.NOT_STARTED


class ReadingProgressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ReadingProgress

    book = factory.SubFactory(BookFactory)
    reading_log = factory.LazyAttribute(lambda obj: obj.book.reading_log)
    progress_percent = 10
