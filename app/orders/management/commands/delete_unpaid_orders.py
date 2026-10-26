from django.core.management.base import BaseCommand
from django.db import transaction

from orders.models import Order

# A payment in one of these means money was taken: such an order is never
# deleted here, whatever its status says — staff sort it out by hand.
MONEY_TAKEN = ('paid', 'refund_needed', 'refunded')


class Command(BaseCommand):
    help = ('Delete the "pending" orders left from before orders were only created once paid. '
            'Pending orders give no stock back (they never held any). '
            'Orders with a payment that took money are kept and listed.')

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List what would be deleted without deleting it.')

    def handle(self, *args, **options):
        with transaction.atomic():
            pending = list(Order.objects.select_for_update().filter(status=Order.Status.PENDING).order_by('pk'))
            keep, delete = [], []
            for order in pending:
                taken = list(order.payments.filter(status__in=MONEY_TAKEN).values_list('pk', 'status'))
                (keep if taken else delete).append((order, taken))

            for order, _ in delete:
                self.stdout.write(f'#{order.pk}  {order.created_at:%Y-%m-%d %H:%M}  {order.full_name}  €{order.total}')
            for order, taken in keep:
                self.stdout.write(self.style.WARNING(
                    f'KEPT #{order.pk}: money was taken (payments {taken}) - check it by hand'))

            if options['dry_run']:
                self.stdout.write(f'{len(delete)} pending order(s) would be deleted, {len(keep)} kept.')
                return
            Order.objects.filter(pk__in=[order.pk for order, _ in delete]).delete()
        self.stdout.write(self.style.SUCCESS(f'Deleted {len(delete)} pending order(s), kept {len(keep)}.'))
