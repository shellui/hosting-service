from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('hosting', '0004_rename_hosting_app_company_name_idx_hosting_app_company_aebbdd_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='app',
            name='created_by_id',
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='app',
            name='expires_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
