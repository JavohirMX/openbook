from django.db.models.signals import post_save
from django.dispatch import receiver

from books.models import Book, _IS_POSTGRESQL


@receiver(post_save, sender=Book)
def update_book_search_vector(sender, instance, **kwargs):
    if not _IS_POSTGRESQL:
        return

    from django.contrib.postgres.search import SearchVector

    Book.objects.filter(pk=instance.pk).update(
        search_vector=(
            SearchVector("title", weight="A", config="english")
            + SearchVector("subtitle", weight="B", config="english")
            + SearchVector("publisher", weight="C", config="english")
        )
    )
