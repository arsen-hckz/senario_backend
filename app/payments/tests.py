from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from orders.models import Order, OrderItem
from products.models import Product, ProductVariant
from .models import Payment
from .viva_client import VivaError

User = get_user_model()


class PaymentsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='buyer@example.com', password='testpass123')
        self.other_user = User.objects.create_user(email='other@example.com', password='testpass123')

        self.product = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), stock=5)
        self.variant = ProductVariant.objects.create(product=self.product, size='M', stock=3)

        self.order = Order.objects.create(
            user=self.user, total=Decimal('24.50'),
            full_name='Buyer Name', address='Addr 1', city='Athens',
            country='GR', postal_code='11111',
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, variant=self.variant,
            product_name='Tee', size='M', price=Decimal('24.50'), qty=2,
        )

    def auth(self, user):
        self.client.force_authenticate(user=user)

    # --- checkout ---

    def test_checkout_requires_auth(self):
        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_checkout_rejects_another_users_order(self):
        self.auth(self.other_user)
        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @patch('payments.viva_client.create_order')
    def test_checkout_creates_payment_and_returns_checkout_url(self, mock_create_order):
        mock_create_order.return_value = '123456789012345'
        self.auth(self.user)

        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('123456789012345', res.data['checkout_url'])
        payment = Payment.objects.get(order=self.order)
        self.assertEqual(payment.viva_order_code, '123456789012345')
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.amount, self.order.total)
        mock_create_order.assert_called_once()
        self.assertEqual(mock_create_order.call_args.kwargs['amount_cents'], 2450)

    @patch('payments.viva_client.create_order')
    def test_checkout_rejects_already_paid_order(self, mock_create_order):
        Payment.objects.create(
            order=self.order, viva_order_code='1', amount=self.order.total,
            status=Payment.Status.PAID,
        )
        self.auth(self.user)

        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        mock_create_order.assert_not_called()

    @patch('payments.viva_client.create_order')
    def test_checkout_returns_502_on_viva_error(self, mock_create_order):
        mock_create_order.side_effect = VivaError('boom')
        self.auth(self.user)

        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')

        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(Payment.objects.filter(order=self.order).exists())

    # --- webhook ---

    def test_webhook_get_returns_verification_key(self):
        with self.settings(VIVA_WEBHOOK_VERIFICATION_KEY='verify-me'):
            res = self.client.get('/api/payments/webhook/viva/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['Key'], 'verify-me')

    def _webhook_event(self, order_code, transaction_id='txn-1'):
        return {'EventTypeId': 1796, 'EventData': {'OrderCode': order_code, 'TransactionId': transaction_id}}

    @patch('payments.viva_client.get_transaction')
    def test_webhook_confirms_payment_order_and_stock_on_verified_transaction(self, mock_get_transaction):
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {
            'orderCode': 999, 'statusId': 'F', 'amount': 2450,
        }

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(payment.viva_transaction_id, 'txn-1')
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.variant.stock, 1)  # 3 - qty(2)

    @patch('payments.viva_client.get_transaction')
    def test_webhook_ignores_amount_mismatch(self, mock_get_transaction):
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {
            'orderCode': 999, 'statusId': 'F', 'amount': 100,  # wrong amount
        }

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    @patch('payments.viva_client.get_transaction')
    def test_webhook_idempotent_when_already_paid(self, mock_get_transaction):
        payment = Payment.objects.create(
            order=self.order, viva_order_code='999', amount=self.order.total,
            status=Payment.Status.PAID, viva_transaction_id='txn-1',
        )

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        mock_get_transaction.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)

    def test_webhook_ignores_unknown_order_code(self):
        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('does-not-exist'), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
