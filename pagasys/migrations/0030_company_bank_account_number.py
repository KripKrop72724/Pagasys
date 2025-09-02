from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('pagasys', '0029_remove_tradelicense_license_expiry_after_issue_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='bank_account_number',
            field=models.CharField(blank=True, max_length=64, help_text='Bank account number used for payroll transactions'),
        ),
    ]
