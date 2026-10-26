from django.core.management.base import BaseCommand

from payments.checkout import KEEP_UNPAID_FOR, delete_old_checkouts


class Command(BaseCommand):
    help = 'Delete unpaid checkouts (customer details of abandoned payments) older than 24 hours. Run hourly from cron.'

    def handle(self, *args, **options):
        count = delete_old_checkouts()
        self.stdout.write(f'Deleted {count} unpaid checkout(s) older than {KEEP_UNPAID_FOR}.')
