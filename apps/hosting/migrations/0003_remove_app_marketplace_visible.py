from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('hosting', '0002_app_name_public_slug'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='app',
            name='marketplace_visible',
        ),
    ]
