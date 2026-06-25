from django.utils.text import slugify

from books.models import Author, Book, BookAuthor, BookGenre, Genre, ReadingLog, ReadingStatus


def get_or_create_author(name: str) -> Author:
    name = name.strip()
    author = Author.objects.filter(name__iexact=name).first()
    if author:
        return author
    return Author.objects.create(name=name)


def get_or_create_genres(names: list[str], source: str) -> list[Genre]:
    genres: list[Genre] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        genre = Genre.objects.filter(name__iexact=name).first()
        if not genre:
            base_slug = slugify(name)[:120] or "genre"
            slug = base_slug
            counter = 1
            while Genre.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            genre = Genre.objects.create(name=name, slug=slug, source=source)
        genres.append(genre)
    return genres


def attach_authors_to_book(book: Book, author_names: list[str]) -> None:
    BookAuthor.objects.filter(book=book).delete()
    for position, name in enumerate(author_names, start=1):
        name = name.strip()
        if not name:
            continue
        author = get_or_create_author(name)
        BookAuthor.objects.create(book=book, author=author, position=position)


def attach_genres_to_book(book: Book, genres: list[Genre]) -> None:
    BookGenre.objects.filter(book=book).delete()
    for genre in genres:
        BookGenre.objects.get_or_create(book=book, genre=genre)


def create_reading_log_for_book(book: Book) -> ReadingLog:
    log, _created = ReadingLog.objects.get_or_create(
        book=book,
        defaults={"status": ReadingStatus.NOT_STARTED},
    )
    return log
