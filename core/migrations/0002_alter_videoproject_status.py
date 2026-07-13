from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="videoproject",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("scripting", "Generating script"),
                    ("ready", "Ready to render"),
                    ("queued", "Queued for render"),
                    ("rendering", "Rendering"),
                    ("rendered", "Rendered"),
                    ("scheduled", "Scheduled"),
                    ("publishing", "Publishing"),
                    ("published", "Published"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="draft",
                max_length=20,
            ),
        )
    ]

