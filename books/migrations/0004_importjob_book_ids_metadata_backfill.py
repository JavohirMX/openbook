from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0003_alter_readinglog_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="book_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name="importjob",
            name="kind",
            field=models.CharField(
                choices=[
                    ("isbns", "ISBNs"),
                    ("goodreads_csv", "Goodreads CSV"),
                    ("metadata_backfill", "Metadata backfill"),
                ],
                max_length=20,
            ),
        ),
    ]
