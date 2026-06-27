from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from books.models import Book, BookNote, Quote, ReadingLog, ReadingStatus, Review, _IS_POSTGRESQL


@receiver(post_save, sender=Book)
def create_reading_log_for_book(sender, instance, created, **kwargs):
    if created:
        ReadingLog.objects.get_or_create(
            book=instance,
            defaults={
                "status": ReadingStatus.NOT_STARTED,
                "total_pages": instance.pages,
            },
        )


def rebuild_book_search_vector(book_id):
    if not _IS_POSTGRESQL:
        return

    from django.contrib.postgres.search import SearchVector
    from django.db.models import Value

    book = Book.objects.prefetch_related("quotes", "private_notes").select_related("review").get(pk=book_id)

    review_text = ""
    if hasattr(book, "review") and book.review.review_text:
        review_text = book.review.review_text

    quote_text = " ".join(q.text for q in book.quotes.all() if q.text)
    note_text = " ".join(n.text for n in book.private_notes.all() if n.text)
    extra_text = " ".join(part for part in (review_text, quote_text, note_text) if part)

    vector = (
        SearchVector("title", weight="A", config="english")
        + SearchVector("subtitle", weight="B", config="english")
        + SearchVector("publisher", weight="C", config="english")
    )
    if extra_text:
        vector += SearchVector(Value(extra_text), weight="D", config="english")

    Book.objects.filter(pk=book_id).update(search_vector=vector)


@receiver(post_save, sender=Book)
def update_book_search_vector(sender, instance, **kwargs):
    rebuild_book_search_vector(instance.pk)


@receiver(post_save, sender=Review)
@receiver(post_save, sender=Quote)
@receiver(post_save, sender=BookNote)
@receiver(post_delete, sender=Quote)
@receiver(post_delete, sender=BookNote)
def update_book_search_on_related(sender, instance, **kwargs):
    rebuild_book_search_vector(instance.book_id)
