from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pagasys", "0002_update_models"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tradelicense",
            name="branch",
        ),
        migrations.AddField(
            model_name="tradelicense",
            name="company",
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="licenses",
                to="pagasys.company",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tradelicense",
            name="branches",
            field=models.ManyToManyField(
                help_text="Which branches this license covers",
                related_name="licenses",
                to="pagasys.branch",
            ),
        ),
    ]
