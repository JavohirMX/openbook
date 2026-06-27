from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from books.import_export import export_csv, export_json


class Command(BaseCommand):
    help = "Export the library to JSON or CSV for scheduled backups."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=("json", "csv"),
            default="json",
            help="Export format (default: json).",
        )
        parser.add_argument(
            "--output",
            "-o",
            required=True,
            help="Output file path.",
        )

    def handle(self, *args, **options):
        output_path = Path(options["output"])
        fmt = options["format"]

        if fmt == "csv":
            content = export_csv()
        else:
            import json

            content = json.dumps(export_json(), indent=2)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Exported library to {output_path}"))
