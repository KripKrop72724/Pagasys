from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('attendance', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='AttAdjustment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('delta_work_min', models.IntegerField(default=0)),
                ('delta_unpaid_break_min', models.IntegerField(default=0)),
                ('delta_paid_break_min', models.IntegerField(default=0)),
                ('delta_ot_regular_min', models.IntegerField(default=0)),
                ('delta_ot_night_min', models.IntegerField(default=0)),
                ('delta_ot_holiday_min', models.IntegerField(default=0)),
                ('override_status', models.CharField(blank=True, max_length=16)),
                ('reason', models.CharField(max_length=255)),
                ('created_by_id', models.IntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('employee', models.ForeignKey(on_delete=models.deletion.CASCADE, to='pagasys.employee')),
            ],
            options={
                'indexes': [models.Index(fields=['employee', 'date'], name='attendance_attadjust_employee_date_idx')],
            },
        ),
    ]
