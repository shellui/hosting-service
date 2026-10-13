"""Register existing hosted origins on the identity OAuth redirect allowlist."""

from __future__ import annotations

import jwt
from django.core.management.base import BaseCommand, CommandError

from apps.hosting.identity_redirects import upsert_hosting_oauth_redirect
from apps.hosting.models import App


class Command(BaseCommand):
    help = (
        'Register hosted app origins with identity-service. '
        'Pass an access token for one company (staff or company owner). '
        'The token company is the only company that is synced.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--access-token',
            required=True,
            help='Identity access token. Company scope comes from its company_id claim.',
        )
        parser.add_argument(
            '--company-id',
            type=int,
            default=None,
            help='Optional check. Must match company_id on the access token.',
        )

    def handle(self, *args, **options):
        token = (options['access_token'] or '').strip()
        if not token:
            raise CommandError('--access-token is required.')
        company_id = _company_id_from_token(token)
        requested = options['company_id']
        if requested is not None and int(requested) != company_id:
            raise CommandError(
                f'--company-id {requested} does not match token company_id {company_id}.',
            )
        apps = list(App.objects.filter(company_id=company_id).order_by('id'))
        if not apps:
            self.stdout.write(f'No hosted apps for company {company_id}.')
            return
        failed = 0
        for app in apps:
            if upsert_hosting_oauth_redirect(app, access_token=token):
                self.stdout.write(f'Registered {app.slug}')
            else:
                failed += 1
                self.stderr.write(f'Failed to register {app.slug}')
        if failed:
            raise CommandError(f'{failed} origin(s) were not registered.')
        self.stdout.write(self.style.SUCCESS(f'Registered {len(apps)} origin(s) for company {company_id}.'))


def _company_id_from_token(token: str) -> int:
    try:
        payload = jwt.decode(
            token,
            options={'verify_signature': False, 'verify_aud': False, 'verify_exp': False},
        )
    except jwt.PyJWTError as exc:
        raise CommandError('Access token is not a JWT.') from exc
    raw = payload.get('company_id') if isinstance(payload, dict) else None
    try:
        company_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise CommandError('Access token is missing company_id.') from exc
    if company_id <= 0:
        raise CommandError('Access token company_id is invalid.')
    return company_id
