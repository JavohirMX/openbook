from django.db import migrations, models

import books.models


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0006_quote"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="cover_image",
            field=models.FileField(blank=True, upload_to=books.models.cover_upload_path),
        ),
    ]
