from django.core.management.base import BaseCommand
from django.db.models import Q

from books.covers import clear_invalid_cover, clear_invalid_stored_cover, download_cover
from books.models import Book


class Command(BaseCommand):
    help = "Download local cover images for books that have cover_url but no cover_image."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-download covers even when cover_image already exists.",
        )
        parser.add_argument(
            "--clean-invalid",
            action="store_true",
            help="Remove placeholder cover images, then download where cover_url exists.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        clean_invalid = options["clean_invalid"]
        verbosity = options["verbosity"]

        if clean_invalid:
            books_with_images = list(Book.all_objects.exclude(cover_image="").iterator())
            total = len(books_with_images)
            self.stdout.write(f"Scanning {total} book(s) with cover images…")
            self.stdout.flush()

            cleaned = 0
            for index, book in enumerate(books_with_images, start=1):
                if clear_invalid_stored_cover(book):
                    cleaned += 1
                    action = "removed placeholder cover"
                else:
                    action = "ok"
                if verbosity >= 1:
                    self.stdout.write(f"  [{index}/{total}] {book.title} — {action}")
                    self.stdout.flush()

            remote_candidates = Book.all_objects.filter(cover_image="").exclude(
                Q(cover_url__isnull=True) | Q(cover_url="")
            )
            remote_total = remote_candidates.count()
            if remote_total:
                self.stdout.write(f"Checking {remote_total} remote cover URL(s)…")
                self.stdout.flush()
                for index, book in enumerate(remote_candidates.iterator(), start=1):
                    if clear_invalid_cover(book, verify_remote=True):
                        cleaned += 1
                        action = "cleared dead URL"
                    else:
                        action = "ok"
                    if verbosity >= 1:
                        self.stdout.write(f"  [{index}/{remote_total}] {book.title} — {action}")
                        self.stdout.flush()

            self.stdout.write(f"Cleaned {cleaned} invalid cover(s).")
            self.stdout.flush()

        queryset = Book.all_objects.all()
        if not force:
            queryset = queryset.filter(cover_image="").exclude(
                Q(cover_url__isnull=True) | Q(cover_url="")
            )

        download_total = queryset.count()
        if clean_invalid and download_total:
            self.stdout.write(f"Downloading covers for {download_total} book(s)…")
            self.stdout.flush()

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
                self.stdout.flush()
            else:
                failed += 1
                self.stderr.write(f"Failed cover for {book.title}")
                self.stderr.flush()

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {downloaded} downloaded, {failed} failed, {skipped} skipped."
            )
        )
