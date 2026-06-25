from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_userprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="embed_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="embed_key",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
