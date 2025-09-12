from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("capture", "0007_add_roster_date_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="punchevent",
            name="processed",
            field=models.BooleanField(default=False, help_text="Final validation completed"),
        ),
        migrations.AddField(
            model_name="punchevent",
            name="processed_at",
            field=models.DateTimeField(blank=True, null=True, help_text="Timestamp when background validation finished"),
        ),
    ]
