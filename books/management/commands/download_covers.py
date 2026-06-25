from django.core.management.base import BaseCommand
from django.db.models import Q

from books.covers import download_cover
from books.models import Book


class Command(BaseCommand):
    help = "Download local cover images for books that have cover_url but no cover_image."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download covers even when cover_image already exists.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        queryset = Book.all_objects.all()
        if not force:
            queryset = queryset.filter(cover_image="").exclude(
                Q(cover_url__isnull=True) | Q(cover_url="")
            )

        downloaded = 0
        failed = 0
        skipped = 0

        for book in queryset.iterator():
            if not force and book.cover_image:
                skipped += 1
                continue
            if not book.cover_url:
                skipped += 1
                continue
            if download_cover(book, force=force):
                downloaded += 1
                self.stdout.write(f"Downloaded cover for {book.title}")
            else:
                failed += 1
                self.stderr.write(f"Failed cover for {book.title}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {downloaded} downloaded, {failed} failed, {skipped} skipped."
            )
        )
