import logging
import time

from django.core.management.base import BaseCommand

from books.import_worker import process_one_pending_job, reclaim_stale_running_jobs

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process pending import jobs from the database queue."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Poll continuously for new jobs.",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=2.0,
            help="Seconds between polls when --loop is set (default: 2).",
        )

    def handle(self, *args, **options):
        if options["loop"]:
            self.stdout.write("Import worker started (loop mode).")
            while True:
                reclaim_stale_running_jobs()
                if not self._process_one():
                    time.sleep(options["interval"])
        else:
            reclaim_stale_running_jobs()
            processed = self._process_one()
            if not processed:
                self.stdout.write("No pending import jobs.")

    def _process_one(self) -> bool:
        if not process_one_pending_job():
            return False
        self.stdout.write(self.style.SUCCESS("Processed one import job."))
        return True
