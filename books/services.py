from django.utils.text import slugify

from books.genre_normalize import METADATA_GENRE_LIMIT, normalize_user_genre_name
from books.models import (
    Author,
    AuthorRole,
    Book,
    BookAuthor,
    BookGenre,
    Genre,
    GenreSource,
    ReadingLog,
    ReadingStatus,
    Series,
)


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


def add_authors_to_book(book: Book, author_names: list[str]) -> None:
    """Attach authors only when the book has none (does not replace existing)."""
    if BookAuthor.objects.filter(book=book).exists():
        return
    seen_author_ids: set[int] = set()
    position = 0
    for name in author_names:
        name = name.strip()
        if not name:
            continue
        author = get_or_create_author(name)
        if author.pk in seen_author_ids:
            continue
        seen_author_ids.add(author.pk)
        position += 1
        BookAuthor.objects.create(book=book, author=author, position=position)


def add_genres_to_book(book: Book, genre_names: list[str], *, source: str) -> None:
    """Attach genres only when the book has none (does not replace existing)."""
    if BookGenre.objects.filter(book=book).exists():
        return
    genres = get_or_create_genres(genre_names[:METADATA_GENRE_LIMIT], source)
    for genre in genres:
        BookGenre.objects.get_or_create(book=book, genre=genre)


def get_or_create_series(name: str) -> Series:
    name = name.strip()
    if not name:
        raise ValueError("Series name is required.")
    series = Series.objects.filter(name__iexact=name).first()
    if series:
        return series
    base_slug = slugify(name)[:120] or "series"
    slug = base_slug
    counter = 1
    while Series.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return Series.objects.create(name=name, slug=slug)


def _unique_slug_for_genre(name: str, *, exclude_pk: int | None = None) -> str:
    base_slug = slugify(name)[:120] or "genre"
    slug = base_slug
    counter = 1
    qs = Genre.objects.filter(slug=slug)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    while qs.exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
        qs = Genre.objects.filter(slug=slug)
        if exclude_pk is not None:
            qs = qs.exclude(pk=exclude_pk)
    return slug


def rename_genre(genre: Genre, new_name: str) -> Genre:
    new_name = normalize_user_genre_name(new_name)
    if not new_name:
        raise ValueError("Genre name is required.")
    conflict = Genre.objects.filter(name__iexact=new_name).exclude(pk=genre.pk).first()
    if conflict:
        raise ValueError(f"A genre named “{conflict.name}” already exists.")
    genre.name = new_name
    genre.slug = _unique_slug_for_genre(new_name, exclude_pk=genre.pk)
    genre.save(update_fields=["name", "slug"])
    return genre


def merge_genres(source: Genre, target: Genre) -> Genre:
    if source.pk == target.pk:
        raise ValueError("Cannot merge a genre into itself.")
    for link in BookGenre.objects.filter(genre=source):
        BookGenre.objects.get_or_create(book=link.book, genre=target)
    source.delete()
    return target


def delete_genre(genre: Genre, *, reassign_to: Genre | None = None) -> None:
    book_count = genre.book_genres.count()
    if book_count and reassign_to is None:
        raise ValueError("Reassign books to another genre before deleting.")
    if reassign_to is not None:
        if reassign_to.pk == genre.pk:
            raise ValueError("Cannot reassign a genre to itself.")
        merge_genres(genre, reassign_to)
        return
    genre.delete()


def attach_authors_to_book(
    book: Book,
    author_names: list[str],
    *,
    editors: list[str] | None = None,
    translators: list[str] | None = None,
    illustrators: list[str] | None = None,
) -> None:
    BookAuthor.objects.filter(book=book).delete()
    seen_keys: set[tuple[int, str]] = set()
    position = 0
    role_groups = [
        (AuthorRole.AUTHOR, author_names),
        (AuthorRole.EDITOR, editors or []),
        (AuthorRole.TRANSLATOR, translators or []),
        (AuthorRole.ILLUSTRATOR, illustrators or []),
    ]
    for role, names in role_groups:
        for name in names:
            name = name.strip()
            if not name:
                continue
            author = get_or_create_author(name)
            key = (author.pk, role)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            position += 1
            BookAuthor.objects.create(book=book, author=author, role=role, position=position)


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


def merge_authors(primary: Author, duplicate_ids: list[int]) -> Author:
    """Reassign books from duplicate authors to primary, then delete duplicates."""
    duplicates = Author.objects.filter(pk__in=duplicate_ids).exclude(pk=primary.pk)
    for duplicate in duplicates:
        for book_author in BookAuthor.objects.filter(author=duplicate):
            exists = BookAuthor.objects.filter(
                book=book_author.book,
                author=primary,
                role=book_author.role,
            ).exists()
            if exists:
                book_author.delete()
            else:
                book_author.author = primary
                book_author.save(update_fields=["author"])
        duplicate.delete()
    return primary


def find_duplicate_author_groups() -> list[list[Author]]:
    """Suggest author merge groups by normalized name."""
    from collections import defaultdict
    import re

    groups: dict[str, list[Author]] = defaultdict(list)
    for author in Author.objects.all():
        key = re.sub(r"[^a-z0-9]", "", author.name.lower())
        if key:
            groups[key].append(author)
    return [authors for authors in groups.values() if len(authors) > 1]
