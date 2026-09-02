from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hosting', '0005_app_preview_expiry'),
    ]

    operations = [
        migrations.DeleteModel(
            name='AppCompatibility',
        ),
    ]
