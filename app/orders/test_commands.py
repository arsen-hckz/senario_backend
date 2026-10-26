from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from payments.models import Payment
from products.models import Product
from .models import Order, OrderItem


class DeleteUnpaidOrdersTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), stock=5)

    def order(self, status, payment_status=None, code=None):
        order = Order.objects.create(status=status, total=Decimal('23.50'), full_name='A', address='B',
                                     city='C', country='Greece', postal_code='1')
        OrderItem.objects.create(order=order, product=self.product, product_name='Tee', price=Decimal('20.00'), qty=1)
        if payment_status:
            Payment.objects.create(order=order, viva_order_code=code, amount=order.total, status=payment_status)
        return order

    def run_command(self, *args):
        out = StringIO()
        call_command('delete_unpaid_orders', *args, stdout=out)
        return out.getvalue()

    def test_deletes_only_pending_orders_where_no_money_was_taken(self):
        plain = self.order('pending')
        abandoned = self.order('pending', 'pending', '1')
        failed = self.order('pending', 'failed', '2')
        paid_but_pending = self.order('pending', 'paid', '3')
        refund_flagged = self.order('pending', 'refund_needed', '4')
        confirmed = self.order('confirmed', 'paid', '5')
        cancelled = self.order('cancelled')

        out = self.run_command('--dry-run')
        self.assertIn('3 pending order(s) would be deleted, 2 kept.', out)
        self.assertIn(f'KEPT #{paid_but_pending.pk}', out)
        self.assertEqual(Order.objects.count(), 7)  # dry run deletes nothing

        out = self.run_command()
        self.assertIn('Deleted 3 pending order(s), kept 2.', out)
        self.assertEqual(
            set(Order.objects.values_list('pk', flat=True)),
            {paid_but_pending.pk, refund_flagged.pk, confirmed.pk, cancelled.pk},
        )
        for gone in (plain, abandoned, failed):
            self.assertFalse(OrderItem.objects.filter(order_id=gone.pk).exists())
        self.assertEqual(set(Payment.objects.values_list('viva_order_code', flat=True)), {'3', '4', '5'})
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)  # pending orders never held stock
