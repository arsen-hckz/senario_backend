from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from orders.models import Order, OrderItem
from products.models import Product, ProductVariant
from .models import Payment

User = get_user_model()

CHARGE = '11111111-1111-4111-8111-111111111111'
REFUND = '22222222-2222-4222-8222-222222222222'
URL = '/api/payments/webhook/viva/'


def reversal(order_code='999', transaction_id=REFUND):
    return {'EventTypeId': 1797, 'EventData': {'OrderCode': order_code, 'TransactionId': transaction_id}}


def refund_txn(**overrides):
    # Field names and units as Viva's Retrieve Transaction returns them:
    # amount in euros, transactionTypeId 4 = card refund.
    txn = {'orderCode': 999, 'statusId': 'F', 'amount': 24.5, 'transactionTypeId': 4}
    txn.update(overrides)
    return txn


class RefundWebhookTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='buyer@example.com', password='x')
        product = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'))
        self.variant = ProductVariant.objects.create(product=product, size='M', stock=1)
        self.order = Order.objects.create(
            user=self.user, total=Decimal('24.50'), status=Order.Status.CONFIRMED,
            full_name='Buyer', address='A 1', city='Athens', country='GR', postal_code='11111',
        )
        OrderItem.objects.create(order=self.order, product=product, variant=self.variant,
                                 product_name='Tee', size='M', price=Decimal('24.50'), qty=2)
        self.payment = Payment.objects.create(
            order=self.order, viva_order_code='999', amount=Decimal('24.50'),
            status=Payment.Status.PAID, viva_transaction_id=CHARGE,
        )

    def tearDown(self):
        cache.clear()

    def refresh(self):
        for obj in (self.order, self.payment, self.variant):
            obj.refresh_from_db()

    @patch('payments.viva_client.get_transaction')
    def test_full_refund_cancels_the_order_and_gives_stock_back(self, get_txn):
        get_txn.return_value = refund_txn()
        res = self.client.post(URL, reversal(), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        get_txn.assert_called_once_with(REFUND)
        self.refresh()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.variant.stock, 3)  # 1 + qty(2)

    @patch('payments.viva_client.get_transaction')
    def test_void_and_negative_amounts_count_too(self, get_txn):
        get_txn.return_value = refund_txn(transactionTypeId='7', amount=-24.5)
        self.client.post(URL, reversal(), format='json')
        self.refresh()
        self.assertEqual(self.order.status, Order.Status.CANCELLED)

    @patch('payments.viva_client.get_transaction')
    def test_repeat_delivery_does_not_give_stock_back_twice(self, get_txn):
        get_txn.return_value = refund_txn()
        self.client.post(URL, reversal(), format='json')
        self.client.post(URL, reversal(), format='json')
        self.refresh()
        self.assertEqual(self.variant.stock, 3)
        self.assertEqual(get_txn.call_count, 1)  # second delivery: payment no longer PAID

    @patch('payments.viva_client.get_transaction')
    def test_the_charge_itself_posted_as_a_reversal_changes_nothing(self, get_txn):
        """Anyone can post to the webhook. The original charge is a real, completed
        transaction of this order, so it must not pass as a refund."""
        get_txn.return_value = refund_txn(transactionTypeId=5)  # 5 = card charge
        self.client.post(URL, reversal(transaction_id='33333333-3333-4333-8333-333333333333'), format='json')
        self.client.post(URL, reversal(transaction_id=CHARGE), format='json')
        self.refresh()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(get_txn.call_count, 1)  # the charge's own id isn't even fetched

    @patch('payments.viva_client.get_transaction')
    def test_unverified_reversals_change_nothing(self, get_txn):
        for txn in (refund_txn(statusId='E'), refund_txn(orderCode=111), refund_txn(transactionTypeId=None),
                    refund_txn(transactionTypeId='x'), refund_txn(amount=None)):
            get_txn.return_value = txn
            self.assertEqual(self.client.post(URL, reversal(), format='json').status_code, status.HTTP_200_OK)
        self.refresh()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)

    @patch('payments.viva_client.get_transaction')
    def test_partial_refund_leaves_the_order_for_staff(self, get_txn):
        get_txn.return_value = refund_txn(amount=10)
        self.client.post(URL, reversal(), format='json')
        self.refresh()
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.payment.status, Payment.Status.PAID)

    @patch('payments.viva_client.get_transaction')
    def test_refund_after_staff_cancelled_closes_the_refund_needed_flag(self, get_txn):
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        self.payment.status = Payment.Status.REFUND_NEEDED
        self.payment.save()
        get_txn.return_value = refund_txn()
        self.client.post(URL, reversal(), format='json')
        self.refresh()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.variant.stock, 1)  # staff's cancel already gave it back (not here)

    @patch('payments.viva_client.get_transaction')
    def test_refund_of_shipped_order_marks_payment_only(self, get_txn):
        self.order.status = Order.Status.SHIPPED
        self.order.save()
        get_txn.return_value = refund_txn()
        self.client.post(URL, reversal(), format='json')
        self.refresh()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertEqual(self.order.status, Order.Status.SHIPPED)
        self.assertEqual(self.variant.stock, 1)

    @patch('payments.viva_client.get_transaction')
    def test_junk_reversal_bodies_are_acked_without_calls(self, get_txn):
        for body in ({'EventTypeId': 1797}, {'EventTypeId': 1797, 'EventData': ['x']},
                     {'EventTypeId': 1797, 'EventData': 'x'}, reversal(transaction_id='../x'),
                     reversal(order_code='nope'), ['x']):
            res = self.client.post(URL, body, format='json')
            self.assertEqual(res.status_code, status.HTTP_200_OK, body)
        get_txn.assert_not_called()
