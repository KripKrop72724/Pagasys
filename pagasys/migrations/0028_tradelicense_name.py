from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagasys", "0027_remove_employee_unified_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradelicense",
            name="name",
            field=models.CharField(
                max_length=100, blank=True, default="", help_text="Trade license name"
            ),
        ),
    ]
