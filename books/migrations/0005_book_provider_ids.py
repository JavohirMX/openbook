from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("books", "0004_importjob_book_ids_metadata_backfill"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="openlibrary_work_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="book",
            name="openlibrary_edition_key",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name="book",
            name="google_books_id",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
