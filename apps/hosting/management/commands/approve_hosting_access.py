"""Approve company hosting access from the shell."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.hosting.models import AccessStatus, CompanyHostingAccess


class Command(BaseCommand):
    help = 'Approve hosting access for a company (bypasses the waitlist).'

    def add_arguments(self, parser):
        parser.add_argument('company_id', type=int, help='Company id from identity-service')
        parser.add_argument(
            '--notes',
            default='Approved via management command',
            help='Optional reviewer notes stored on the access row',
        )

    def handle(self, *args, **options):
        company_id = options['company_id']
        notes = (options.get('notes') or '').strip()
        now = timezone.now()

        access, created = CompanyHostingAccess.objects.get_or_create(
            company_id=company_id,
            defaults={
                'status': AccessStatus.APPROVED,
                'reviewed_at': now,
                'notes': notes,
            },
        )
        if not created and access.status == AccessStatus.APPROVED:
            self.stdout.write(self.style.WARNING(f'Company {company_id} is already approved.'))
            return

        access.status = AccessStatus.APPROVED
        access.reviewed_at = now
        if notes:
            access.notes = notes
        access.save(update_fields=['status', 'reviewed_at', 'notes'])

        action = 'Created and approved' if created else 'Approved'
        self.stdout.write(self.style.SUCCESS(f'{action} hosting access for company {company_id}.'))
