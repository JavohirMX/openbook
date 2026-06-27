from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("books", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="importjob",
            name="cancel_requested",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name="importjob",
            name="status",
            field=models.CharField(
                choices=[
                    ("awaiting_confirmation", "Awaiting confirmation"),
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                    ("cancelled", "Cancelled"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
    ]
