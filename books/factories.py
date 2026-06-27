import factory

from books.models import (
    Author,
    Book,
    BookAuthor,
    BookGenre,
    BookNote,
    BookshelfItem,
    Genre,
    MetadataMatchProposal,
    MetadataMatchProposalStatus,
    Quote,
    ReadingLog,
    ReadingProgress,
    ReadingStatus,
    Review,
    Series,
    Shelf,
)


class AuthorFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Author

    name = factory.Faker("name")


class SeriesFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Series

    name = factory.Sequence(lambda n: f"Series {n}")
    slug = factory.Sequence(lambda n: f"series-{n}")


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
    review_text = ""


class QuoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Quote

    book = factory.SubFactory(BookFactory)
    text = factory.Faker("sentence")


class BookNoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BookNote

    book = factory.SubFactory(BookFactory)
    text = "Private note text"


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


class MetadataMatchProposalFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = MetadataMatchProposal

    book = factory.SubFactory(BookFactory)
    candidate = factory.LazyFunction(
        lambda: {
            "title": "Proposed Title",
            "authors": ["Author One"],
            "isbn_13": "9780143127741",
            "cover_url": "https://example.com/cover.jpg",
        }
    )
    score = 0.85
    alternates = factory.LazyFunction(list)
    status = MetadataMatchProposalStatus.PENDING
    source_summary = "open_library+google_books"
