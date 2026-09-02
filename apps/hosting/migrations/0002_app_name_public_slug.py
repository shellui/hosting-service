"""Split company-scoped app name from auto-generated public URL slug."""

from __future__ import annotations

import secrets
import string

from django.db import migrations, models


def _generate_public_slug(existing: set[str]) -> str:
    alphabet = string.ascii_lowercase + string.digits
    for _ in range(64):
        first = secrets.choice(string.ascii_lowercase)
        rest = ''.join(secrets.choice(alphabet) for _ in range(11))
        candidate = f'{first}{rest}'
        if candidate not in existing:
            existing.add(candidate)
            return candidate
    raise RuntimeError('Could not generate a unique public slug during migration.')


def forwards(apps, schema_editor):
    App = apps.get_model('hosting', 'App')
    existing: set[str] = set(App.objects.values_list('slug', flat=True))
    for app in App.objects.all().order_by('created_at'):
        app.name = app.slug
        app.slug = _generate_public_slug(existing)
        app.save(update_fields=['name', 'slug'])


class Migration(migrations.Migration):
    dependencies = [
        ('hosting', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='app',
            name='name',
            field=models.SlugField(default='pending', max_length=63),
            preserve_default=False,
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name='app',
            options={'ordering': ['name']},
        ),
        migrations.RemoveIndex(
            model_name='app',
            name='hosting_app_company_faa8ff_idx',
        ),
        migrations.AddConstraint(
            model_name='app',
            constraint=models.UniqueConstraint(
                fields=('company_id', 'name'),
                name='hosting_app_company_name_uniq',
            ),
        ),
        migrations.AddIndex(
            model_name='app',
            index=models.Index(fields=['company_id', 'name'], name='hosting_app_company_name_idx'),
        ),
    ]
