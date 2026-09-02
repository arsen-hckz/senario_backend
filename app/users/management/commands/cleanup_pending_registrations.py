from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import PendingRegistration


class Command(BaseCommand):
    help = 'Delete pending registrations that were never verified within N days of signing up.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=7,
            help='Delete pending registrations older than this many days (default: 7).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List pending registrations that would be deleted without deleting them.',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])
        queryset = PendingRegistration.objects.filter(created_at__lt=cutoff)
        count = queryset.count()

        if options['dry_run']:
            for pending in queryset:
                self.stdout.write(f'{pending.email} (registered {pending.created_at:%Y-%m-%d})')
            self.stdout.write(self.style.WARNING(f'{count} pending registration(s) would be deleted.'))
            return

        queryset.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {count} pending registration(s) older than {options["days"]} day(s).'))
