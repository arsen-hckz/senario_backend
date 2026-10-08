from decimal import Decimal
from unittest.mock import Mock, patch

import requests

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from orders.models import Order, OrderItem
from products.models import Product, ProductVariant
from . import viva_client
from .models import Payment
from .viva_client import VivaError

User = get_user_model()

# Viva transaction ids are GUIDs.
TXN_1 = '11111111-1111-4111-8111-111111111111'
TXN_A = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
TXN_B = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


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

    def _webhook_event(self, order_code, transaction_id=TXN_1, event_type=1796):
        return {'EventTypeId': event_type, 'EventData': {'OrderCode': order_code, 'TransactionId': transaction_id}}

    @patch('payments.viva_client.get_transaction')
    def test_webhook_confirms_payment_order_and_stock_on_verified_transaction(self, mock_get_transaction):
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {
            'orderCode': 999, 'statusId': 'F', 'amount': 24.5,  # euros, as Viva returns it
        }

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(payment.viva_transaction_id, TXN_1)
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.variant.stock, 1)  # 3 - qty(2)

    @patch('payments.viva_client.get_transaction')
    def test_webhook_ignores_amount_mismatch(self, mock_get_transaction):
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {
            'orderCode': 999, 'statusId': 'F', 'amount': 1.0,  # wrong amount
        }

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    @patch('payments.viva_client.get_transaction')
    def test_webhook_idempotent_when_already_paid(self, mock_get_transaction):
        payment = Payment.objects.create(
            order=self.order, viva_order_code='999', amount=self.order.total,
            status=Payment.Status.PAID, viva_transaction_id=TXN_1,
        )

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        mock_get_transaction.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)

    def test_webhook_ignores_unknown_order_code(self):
        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('does-not-exist'), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    @patch('payments.viva_client.get_transaction')
    def test_webhook_rejects_cents_amount_from_old_assumption(self, mock_get_transaction):
        """Regression: 2450 'cents' must not match a 24.50 order — Viva returns euros."""
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {'orderCode': 999, 'statusId': 'F', 'amount': 2450}

        self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    def test_to_cents_handles_float_euros_without_drift(self):
        from .viva_client import to_cents
        self.assertEqual(to_cents(19.99), 1999)
        self.assertEqual(to_cents(0.1), 10)
        self.assertEqual(to_cents(Decimal('24.50')), 2450)

    @patch('payments.viva_client.create_order')
    def test_checkout_rejects_cancelled_order(self, mock_create_order):
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        self.auth(self.user)

        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        mock_create_order.assert_not_called()

    @patch('payments.viva_client.create_order')
    def test_checkout_rejects_order_when_stock_ran_out(self, mock_create_order):
        self.variant.stock = 1  # order wants 2
        self.variant.save()
        self.auth(self.user)

        res = self.client.post(f'/api/payments/checkout/{self.order.id}/')

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        mock_create_order.assert_not_called()

    @patch('payments.viva_client.get_transaction')
    def test_webhook_records_payment_even_if_oversold(self, mock_get_transaction):
        """Customer was already charged: a stock shortfall must not abort recording it."""
        self.variant.stock = 1  # order wants 2
        self.variant.save()
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {'orderCode': 999, 'statusId': 'F', 'amount': 24.5}

        res = self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.status, Order.Status.CONFIRMED)
        self.assertEqual(self.variant.stock, 0)

    @patch('payments.viva_client.get_transaction')
    def test_second_payment_for_same_order_is_flagged_for_refund(self, mock_get_transaction):
        """Customer paid in two tabs: confirm once, decrement stock once, flag the other."""
        first = Payment.objects.create(order=self.order, viva_order_code='111', amount=self.order.total)
        second = Payment.objects.create(order=self.order, viva_order_code='222', amount=self.order.total)

        mock_get_transaction.return_value = {'orderCode': 111, 'statusId': 'F', 'amount': 24.5}
        self.client.post('/api/payments/webhook/viva/', self._webhook_event('111', TXN_A), format='json')
        mock_get_transaction.return_value = {'orderCode': 222, 'statusId': 'F', 'amount': 24.5}
        self.client.post('/api/payments/webhook/viva/', self._webhook_event('222', TXN_B), format='json')

        first.refresh_from_db()
        second.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(first.status, Payment.Status.PAID)
        self.assertEqual(second.status, Payment.Status.REFUND_NEEDED)
        self.assertEqual(second.viva_transaction_id, TXN_B)
        self.assertEqual(self.variant.stock, 1)  # decremented once: 3 - 2

    @patch('payments.viva_client.get_transaction')
    def test_payment_for_cancelled_order_is_flagged_for_refund(self, mock_get_transaction):
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        self.order.status = Order.Status.CANCELLED
        self.order.save()
        mock_get_transaction.return_value = {'orderCode': 999, 'statusId': 'F', 'amount': 24.5}

        self.client.post('/api/payments/webhook/viva/', self._webhook_event('999'), format='json')

        payment.refresh_from_db()
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUND_NEEDED)
        self.assertEqual(self.order.status, Order.Status.CANCELLED)
        self.assertEqual(self.variant.stock, 3)

    def test_webhook_is_not_rate_limited(self):
        from .views import VivaWebhookView
        self.assertEqual(tuple(VivaWebhookView.throttle_classes), ())

    @patch('payments.viva_client.get_transaction')
    def test_webhook_ignores_reversal_events(self, mock_get_transaction):
        """A refund (EventTypeId 1797) shares the order's OrderCode and must never confirm it."""
        payment = Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)
        mock_get_transaction.return_value = {'orderCode': 999, 'statusId': 'F', 'amount': 24.5}

        self.client.post('/api/payments/webhook/viva/', self._webhook_event('999', event_type=1797), format='json')

        mock_get_transaction.assert_not_called()
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)

    @patch('payments.viva_client.get_transaction')
    def test_webhook_ignores_non_guid_transaction_id(self, mock_get_transaction):
        Payment.objects.create(order=self.order, viva_order_code='999', amount=self.order.total)

        res = self.client.post(
            '/api/payments/webhook/viva/', self._webhook_event('999', '../../admin'), format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        mock_get_transaction.assert_not_called()


class VivaClientTests(APITestCase):
    def setUp(self):
        cache.clear()

    def _response(self, status_code, payload=None):
        res = Mock(status_code=status_code, ok=200 <= status_code < 300, text='')
        res.json.return_value = payload or {}
        return res

    @patch('payments.viva_client.requests.request')
    @patch('payments.viva_client.requests.post')
    def test_retries_once_with_fresh_token_after_401(self, mock_post, mock_request):
        mock_post.side_effect = [
            self._response(200, {'access_token': 'old', 'expires_in': 3600}),
            self._response(200, {'access_token': 'new', 'expires_in': 3600}),
        ]
        mock_request.side_effect = [
            self._response(401),
            self._response(200, {'statusId': 'F'}),
        ]

        txn = viva_client.get_transaction(TXN_1)

        self.assertEqual(txn, {'statusId': 'F'})
        self.assertEqual(mock_request.call_args_list[1].kwargs['headers']['Authorization'], 'Bearer new')

    @patch('payments.viva_client.requests.post')
    def test_network_failure_becomes_viva_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError('down')
        with self.assertRaises(VivaError):
            viva_client.get_access_token()

    def test_token_cache_is_scoped_to_environment_and_client(self):
        with self.settings(VIVA_ENV='demo', VIVA_CLIENT_ID='a'):
            demo_key = viva_client._token_cache_key()
        with self.settings(VIVA_ENV='production', VIVA_CLIENT_ID='a'):
            prod_key = viva_client._token_cache_key()
        self.assertNotEqual(demo_key, prod_key)


class OperationalSafetyTests(APITestCase):
    def test_tests_use_their_own_redis_database(self):
        from django.conf import settings
        self.assertTrue(settings.REDIS_URL.endswith('/15'))

    def test_refund_needed_emails_staff(self):
        from django.core import mail
        from django.test import override_settings
        import logging
        handler = next(h for h in logging.getLogger('payments').handlers if h.__class__.__name__ == 'AdminEmailHandler')
        # require_debug_false passes in tests (DEBUG is False under the test runner).
        with override_settings(ADMINS=[('Staff', 'staff@example.com')]):
            logging.getLogger('payments.views').error('Payment #1 for Order #1 needs a refund')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('staff@example.com', mail.outbox[0].to)
        self.assertIn('needs a refund', mail.outbox[0].subject)
        self.assertIsNotNone(handler)
