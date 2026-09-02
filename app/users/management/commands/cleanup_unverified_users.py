from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = 'Delete accounts that never verified their email within N days of registering.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=7,
            help='Delete unverified accounts older than this many days (default: 7).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='List accounts that would be deleted without deleting them.',
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options['days'])
        queryset = User.objects.filter(is_email_verified=False, is_staff=False, created_at__lt=cutoff)
        count = queryset.count()

        if options['dry_run']:
            for user in queryset:
                self.stdout.write(f'{user.email} (registered {user.created_at:%Y-%m-%d})')
            self.stdout.write(self.style.WARNING(f'{count} unverified account(s) would be deleted.'))
            return

        queryset.delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {count} unverified account(s) older than {options["days"]} day(s).'))
