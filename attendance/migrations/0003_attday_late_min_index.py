from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0002_attadjustment"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="attday",
            index=models.Index(fields=["date", "late_min"], name="attendance_date_late_min_idx"),
        ),
    ]
