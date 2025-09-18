from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pagasys", "0033_alter_employee_c3_id_alter_employee_payment_status_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="is_only_company",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When enabled, this instance represents the sole company and "
                    "blocks creation of any additional companies."
                ),
            ),
        ),
    ]
