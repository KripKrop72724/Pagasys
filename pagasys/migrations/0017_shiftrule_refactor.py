from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('pagasys', '0016_attpair_source_alter_attpair_duration_min_and_more'),
    ]

    operations = [
        migrations.DeleteModel(name='ShiftRule'),
        migrations.CreateModel(
            name='ShiftRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(help_text='Rule kind', max_length=50)),
                ('value', models.CharField(help_text='Rule value', max_length=100)),
                ('shift', models.ForeignKey(help_text='Shift this rule applies to', on_delete=models.CASCADE, related_name='rules', to='pagasys.shifttemplate')),
            ],
            options={'verbose_name': 'shift rule', 'verbose_name_plural': 'shift rules', 'ordering': ['shift_id', 'kind'], 'unique_together': {('shift', 'kind')}},
        ),
    ]
