from django.apps import AppConfig


class BooksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "books"

    def ready(self):
        import books.signals  # noqa: F401

        from django.conf import settings

        if settings.DEBUG and getattr(settings, "IMPORT_JOB_AUTO_PROCESS", True):
            from books.import_worker import schedule_import_processing

            schedule_import_processing()
