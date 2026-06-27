from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0002_importjob_cancel"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="cancel_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
