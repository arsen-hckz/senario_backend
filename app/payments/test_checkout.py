"""Orders only exist once Viva confirms the payment: checkout holds the
basket, and the webhook turns it into a confirmed Order."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from cart.models import Cart, CartItem
from orders.models import Order
from products.models import Product, ProductVariant
from .models import Checkout, Payment
from .viva_client import VivaError

User = get_user_model()

ADDRESS = {
    'full_name': 'Buyer Name', 'address': 'Addr 1', 'city': 'Athens',
    'country': 'GR', 'postal_code': '11111', 'phone': '+30 690 000 0000',
}
GUEST = dict(ADDRESS, full_name='Guest Buyer', email='guest@example.com', country='Greece')
CHARGE = '11111111-1111-4111-8111-111111111111'
REFUND = '22222222-2222-4222-8222-222222222222'
WEBHOOK = '/api/payments/webhook/viva/'
# Viva order codes are unique: one per payment started.
CODES = [str(100000000000000 + n) for n in range(1, 41)]


def payment_event(order_code, transaction_id=CHARGE, event_type=1796):
    return {'EventTypeId': event_type, 'EventData': {'OrderCode': order_code, 'TransactionId': transaction_id}}


def charged(order_code, amount):
    # Field names and units as Viva's Retrieve Transaction returns them: euros.
    return {'orderCode': int(order_code), 'statusId': 'F', 'amount': amount, 'transactionTypeId': 5}


@override_settings(SHIPPING_FEE='3.50', FREE_SHIPPING_OVER='')
@patch('payments.viva_client.create_order', side_effect=CODES)
class SignedInCheckoutTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='buyer@example.com', password='testpass123')
        self.client.force_authenticate(user=self.user)
        self.product = Product.objects.create(
            name='Tee', slug='tee', price=Decimal('20.00'), sale_price=Decimal('15.00'), stock=5,
        )
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, qty=2)

    def tearDown(self):
        cache.clear()

    def checkout(self, **overrides):
        return self.client.post('/api/payments/checkout/', dict(ADDRESS, **overrides), format='json')

    def test_requires_an_account(self, viva):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.checkout().status_code, status.HTTP_401_UNAUTHORIZED)
        viva.assert_not_called()

    def test_starts_a_payment_without_creating_an_order(self, viva):
        res = self.checkout()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn(CODES[0], res.data['checkout_url'])
        self.assertFalse(Order.objects.exists())
        self.assertTrue(self.cart.items.exists())  # only emptied once paid

        checkout = Checkout.objects.get()
        self.assertEqual((res.data['checkout_id'], res.data['token']), (checkout.pk, checkout.token))
        self.assertGreaterEqual(len(checkout.token), 40)
        # 2 x 15.00 sale price + 3.50 delivery, priced on the server.
        self.assertEqual((checkout.shipping, checkout.total), (Decimal('3.50'), Decimal('33.50')))
        self.assertEqual(checkout.items, [{
            'product_id': self.product.pk, 'variant_id': None, 'product_name': 'Tee',
            'size': '', 'price': '15.00', 'qty': 2,
        }])
        self.assertEqual((checkout.user, checkout.email, checkout.country), (self.user, 'buyer@example.com', 'Greece'))

        payment = Payment.objects.get()
        self.assertEqual((payment.checkout, payment.order, payment.amount), (checkout, None, Decimal('33.50')))
        self.assertEqual(viva.call_args.kwargs['amount_cents'], 3350)
        self.assertEqual(viva.call_args.kwargs['customer_email'], 'buyer@example.com')

    def test_checkout_email_overrides_the_account_email(self, viva):
        self.checkout(email='gift@example.com')
        self.assertEqual(Checkout.objects.get().email, 'gift@example.com')

    def test_bad_details_are_refused_before_viva_is_called(self, viva):
        for overrides in ({'phone': ''}, {'phone': 'call me'}, {'country': 'Cyprus'}, {'full_name': ''}):
            self.assertEqual(self.checkout(**overrides).status_code, status.HTTP_400_BAD_REQUEST, overrides)
        viva.assert_not_called()
        self.assertFalse(Checkout.objects.exists())

    def test_unbuyable_carts_are_refused(self, viva):
        ProductVariant.objects.create(product=self.product, size='M', stock=5)
        res = self.checkout()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Please choose a size for: Tee', str(res.data))
        ProductVariant.objects.all().delete()

        Product.objects.filter(pk=self.product.pk).update(stock=1)
        self.assertEqual(self.checkout().status_code, status.HTTP_400_BAD_REQUEST)
        Product.objects.filter(pk=self.product.pk).update(stock=5, is_active=False)
        self.assertEqual(self.checkout().status_code, status.HTTP_400_BAD_REQUEST)
        self.cart.items.all().delete()
        self.assertEqual(self.checkout().status_code, status.HTTP_400_BAD_REQUEST)

        viva.assert_not_called()
        self.assertFalse(Checkout.objects.exists())

    def test_viva_failure_leaves_nothing_behind(self, viva):
        viva.side_effect = VivaError('down')
        with self.assertLogs('payments.views', level='ERROR'):
            res = self.checkout()
        self.assertEqual(res.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(Checkout.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(Order.objects.exists())
        self.assertTrue(self.cart.items.exists())

    def test_is_rate_limited_per_account(self, viva):
        codes = [self.checkout().status_code for _ in range(21)]
        self.assertEqual(codes[:20], [status.HTTP_201_CREATED] * 20)
        self.assertEqual(codes[20], status.HTTP_429_TOO_MANY_REQUESTS)

    def test_unpaid_checkouts_are_deleted_after_24_hours(self, viva):
        self.checkout()
        self.checkout()
        recent, old = Checkout.objects.order_by('pk')
        Checkout.objects.filter(pk=recent.pk).update(created_at=timezone.now() - timedelta(hours=23))
        Checkout.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=25))
        self.checkout()
        self.assertTrue(Checkout.objects.filter(pk=recent.pk).exists())
        self.assertFalse(Checkout.objects.filter(pk=old.pk).exists())
        # Kept so a payment that still arrived for it raises a refund alert.
        self.assertEqual(Payment.objects.filter(checkout=None).count(), 1)

    def test_hourly_command_deletes_old_unpaid_checkouts_only(self, viva):
        from io import StringIO
        from django.core.management import call_command
        self.checkout()
        self.checkout()
        unpaid, paid = Checkout.objects.order_by('pk')
        order = Order.objects.create(user=self.user, total=1, status=Order.Status.CONFIRMED, full_name='A',
                                     address='B', city='C', country='Greece', postal_code='1')
        Checkout.objects.filter(pk=paid.pk).update(order=order)
        Checkout.objects.update(created_at=timezone.now() - timedelta(days=30))
        out = StringIO()
        call_command('delete_old_checkouts', stdout=out)
        self.assertIn('Deleted 1 unpaid checkout(s)', out.getvalue())
        self.assertEqual(list(Checkout.objects.values_list('pk', flat=True)), [paid.pk])

    def test_removed_endpoints_are_gone(self, viva):
        self.assertEqual(self.client.post('/api/orders/create/', ADDRESS, format='json').status_code, 404)
        self.assertEqual(self.client.post('/api/orders/guest/', GUEST, format='json').status_code, 404)


@override_settings(SHIPPING_FEE='3.50', FREE_SHIPPING_OVER='')
@patch('payments.viva_client.create_order', side_effect=CODES)
class GuestCheckoutTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.tee = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), stock=5)

    def tearDown(self):
        cache.clear()

    def checkout(self, items=None, **overrides):
        body = dict(GUEST, items=items if items is not None else [{'product_id': self.tee.id, 'qty': 2}], **overrides)
        return self.client.post('/api/payments/guest-checkout/', body, format='json')

    def test_starts_a_payment_without_an_account_or_an_order(self, viva):
        res = self.checkout(items=[{'product_id': self.tee.id, 'qty': 2, 'price': '0.01'}])
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        checkout = Checkout.objects.get()
        self.assertIsNone(checkout.user)
        self.assertEqual((checkout.total, checkout.email), (Decimal('43.50'), 'guest@example.com'))
        kwargs = viva.call_args.kwargs
        self.assertEqual((kwargs['amount_cents'], kwargs['customer_email']), (4350, 'guest@example.com'))
        self.assertFalse(Order.objects.exists())

    def test_bad_requests_are_refused(self, viva):
        self.assertEqual(self.checkout(email='').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.checkout(items=[]).status_code, status.HTTP_400_BAD_REQUEST)
        res = self.checkout(items=[{'product_id': self.tee.id, 'qty': 6}])
        self.assertEqual(res.data['items'], ['Some items are no longer available: Tee: Only 5 left in stock. Please review your cart.'])
        self.assertEqual(self.checkout(country='Cyprus').status_code, status.HTTP_400_BAD_REQUEST)
        for junk in ('x', [1], [{'product_id': self.tee.id, 'qty': 0}], [{'product_id': 1e10, 'qty': 1}],
                     [{'product_id': 10 ** 20, 'qty': 1}], [{'product_id': self.tee.id, 'variant_id': 10 ** 20, 'qty': 1}]):
            self.assertEqual(self.checkout(items=junk).status_code, status.HTTP_400_BAD_REQUEST, junk)
        viva.assert_not_called()
        self.assertFalse(Checkout.objects.exists())

    def test_is_rate_limited_per_ip(self, viva):
        codes = [self.checkout(items=[{'product_id': self.tee.id, 'qty': 1}]).status_code for _ in range(21)]
        self.assertEqual(codes[-1], status.HTTP_429_TOO_MANY_REQUESTS)


@override_settings(SHIPPING_FEE='3.50', FREE_SHIPPING_OVER='', FRONTEND_URL='https://shop.example')
@patch('payments.viva_client.get_transaction')
@patch('payments.viva_client.create_order', side_effect=CODES)
class PaidCheckoutBecomesAnOrderTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='buyer@example.com', password='testpass123')
        self.hoodie = Product.objects.create(name='Hoodie', slug='hoodie', price=Decimal('50.00'), stock=0)
        self.m = ProductVariant.objects.create(product=self.hoodie, size='M', stock=3)
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.hoodie, variant=self.m, qty=2)

    def tearDown(self):
        cache.clear()

    def signed_in_checkout(self):
        self.client.force_authenticate(user=self.user)
        res = self.client.post('/api/payments/checkout/', ADDRESS, format='json')
        self.client.force_authenticate(user=None)
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        return res.data

    def guest_checkout(self):
        res = self.client.post('/api/payments/guest-checkout/', dict(
            GUEST, items=[{'product_id': self.hoodie.id, 'variant_id': self.m.id, 'qty': 1}],
        ), format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        return res.data

    def pay(self, order_code, amount, transaction_id=CHARGE):
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(WEBHOOK, payment_event(order_code, transaction_id), format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def status_of(self, data, token=None):
        return self.client.get(f"/api/payments/checkout/{data['checkout_id']}/",
                               HTTP_X_CHECKOUT_TOKEN=data['token'] if token is None else token)

    def test_verified_payment_creates_the_confirmed_order(self, viva, get_txn):
        data = self.signed_in_checkout()
        get_txn.return_value = charged(CODES[0], 103.5)
        self.pay(CODES[0], 103.5)

        order = Order.objects.get()
        self.assertEqual((order.status, order.user, order.access_token), (Order.Status.CONFIRMED, self.user, ''))
        self.assertEqual((order.total, order.shipping, order.email, order.phone), (
            Decimal('103.50'), Decimal('3.50'), 'buyer@example.com', '+30 690 000 0000'))
        item = order.items.get()
        self.assertEqual((item.product, item.variant, item.product_name, item.size, item.price, item.qty),
                         (self.hoodie, self.m, 'Hoodie', 'M', Decimal('50.00'), 2))
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 1)

        payment = Payment.objects.get()
        self.assertEqual((payment.status, payment.order, payment.viva_transaction_id), (Payment.Status.PAID, order, CHARGE))
        self.assertEqual(Checkout.objects.get().order, order)
        self.assertFalse(self.cart.items.exists())

        customer, alert = mail.outbox
        self.assertEqual(customer.to, ['buyer@example.com'])
        self.assertIn(f'order #{order.pk} is confirmed', customer.subject)
        self.assertIn('Email us at Senarioproject@gmail.com.', customer.body)
        self.assertNotIn('reply to this email', customer.body.lower())

        # The shop hears about it, with what it needs to pack and ship.
        self.assertEqual(alert.to, ['Senarioproject@gmail.com'])
        self.assertEqual(alert.subject, f'New order #{order.pk} — €103.50')
        for text in ('2 x Hoodie (M)', 'Buyer Name', 'buyer@example.com', '+30 690 000 0000',
                     'Addr 1', '11111 Athens, Greece', 'https://shop.example/admin'):
            self.assertIn(text, alert.body)
        self.assertNotIn('(guest)', alert.body)
        html = alert.alternatives[0][0]
        self.assertNotIn('Hey', html)  # no customer-style greeting for the shop

        res = self.status_of(data)
        self.assertEqual(res.data, {'paid': True, 'order_id': order.pk, 'order_status': 'confirmed', 'is_guest': False})
        # The customer sees it in My Orders now — and not before.
        self.client.force_authenticate(user=self.user)
        self.assertEqual([o['id'] for o in self.client.get('/api/orders/').data['results']], [order.pk])

    def test_nothing_is_an_order_before_payment(self, viva, get_txn):
        data = self.signed_in_checkout()
        self.guest_checkout()
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.status_of(data).data, {'paid': False, 'order_id': None, 'order_status': None, 'is_guest': False})
        staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.client.force_authenticate(user=staff)
        self.assertEqual(self.client.get('/api/orders/admin/').data, [])
        self.client.force_authenticate(user=self.user)
        self.assertEqual(self.client.get('/api/orders/').data['results'], [])

    def test_only_what_was_paid_for_leaves_the_cart(self, viva, get_txn):
        self.signed_in_checkout()
        tee = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), stock=5)
        CartItem.objects.create(cart=self.cart, product=tee, qty=1)  # added while paying
        get_txn.return_value = charged(CODES[0], 103.5)
        self.pay(CODES[0], 103.5)
        self.assertEqual([i.product for i in self.cart.items.all()], [tee])

    def test_guest_payment_creates_an_order_opened_with_the_checkout_secret(self, viva, get_txn):
        data = self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)

        order = Order.objects.get()
        self.assertIsNone(order.user)
        self.assertEqual(order.access_token, data['token'])
        self.assertEqual(self.status_of(data).data['is_guest'], True)
        res = self.client.get(f'/api/orders/guest/{order.pk}/', HTTP_X_ORDER_TOKEN=data['token'])
        self.assertEqual((res.status_code, res.data['status']), (200, 'confirmed'))
        customer, alert = mail.outbox
        self.assertEqual(customer.to, ['guest@example.com'])
        self.assertIn(f"https://shop.example/order?id={order.pk}#t={data['token']}", customer.body)
        self.assertIn('Shipping  €3.50', customer.body)
        self.assertIn('Guest Buyer (guest)', alert.body)
        self.assertNotIn(data['token'], alert.body)  # the guest's secret stays with the guest

    def test_account_order_is_not_reachable_with_the_checkout_secret(self, viva, get_txn):
        data = self.signed_in_checkout()
        get_txn.return_value = charged(CODES[0], 103.5)
        self.pay(CODES[0], 103.5)
        order = Order.objects.get()
        res = self.client.get(f'/api/orders/guest/{order.pk}/', HTTP_X_ORDER_TOKEN=data['token'])
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_checkout_status_needs_its_secret(self, viva, get_txn):
        data = self.guest_checkout()
        for wrong in ('', 'x' * 43, data['token'][:-1], self.signed_in_checkout()['token']):
            self.assertEqual(self.status_of(data, token=wrong).status_code, status.HTTP_404_NOT_FOUND, wrong)
        res = self.client.get('/api/payments/checkout/999999/', HTTP_X_CHECKOUT_TOKEN=data['token'])
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = self.client.get(f"/api/payments/checkout/{data['checkout_id']}/")
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(CORS_ALLOWED_ORIGINS=['https://www.snr-project.gr'])
    def test_browsers_may_send_the_checkout_secret_header(self, viva, get_txn):
        """The storefront is another origin: without this the return page's poll is blocked."""
        data = self.guest_checkout()
        res = self.client.options(
            f"/api/payments/checkout/{data['checkout_id']}/",
            HTTP_ORIGIN='https://www.snr-project.gr',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='GET',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='x-checkout-token',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('x-checkout-token', res.headers['Access-Control-Allow-Headers'])
        self.assertEqual(res.headers['Access-Control-Allow-Origin'], 'https://www.snr-project.gr')

    def test_repeated_deliveries_make_one_order_and_one_email(self, viva, get_txn):
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        self.pay(CODES[0], 53.5, transaction_id='33333333-3333-4333-8333-333333333333')
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)  # one confirmation + one shop alert, not more
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 2)

    def test_unverified_payments_create_no_order(self, viva, get_txn):
        self.guest_checkout()
        for txn in (
            charged(CODES[0], 1.0),                      # wrong amount
            charged(CODES[0], 5350),                     # cents, not euros
            dict(charged(CODES[0], 53.5), statusId='E'),  # failed
            charged(CODES[1], 53.5),                     # another order code
        ):
            get_txn.return_value = txn
            cache.clear()
            self.pay(CODES[0], 53.5)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(Payment.objects.get().status, Payment.Status.PENDING)

    def test_a_refund_event_never_creates_the_order(self, viva, get_txn):
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(WEBHOOK, payment_event(CODES[0], REFUND, event_type=1797), format='json')
        get_txn.assert_not_called()
        self.assertFalse(Order.objects.exists())

    def test_order_keeps_the_price_that_was_paid(self, viva, get_txn):
        self.guest_checkout()
        Product.objects.filter(pk=self.hoodie.pk).update(price=Decimal('80.00'))
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        order = Order.objects.get()
        self.assertEqual((order.total, order.items.get().price), (Decimal('53.50'), Decimal('50.00')))

    def test_deleted_product_still_makes_the_paid_order(self, viva, get_txn):
        self.guest_checkout()
        self.hoodie.delete()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        item = Order.objects.get().items.get()
        self.assertEqual((item.product, item.variant, item.product_name, item.size), (None, None, 'Hoodie', 'M'))

    def test_oversold_payment_is_still_an_order_and_alerts_staff(self, viva, get_txn):
        self.guest_checkout()
        ProductVariant.objects.filter(pk=self.m.pk).update(stock=0)
        get_txn.return_value = charged(CODES[0], 53.5)
        with self.assertLogs('payments.views', level='ERROR') as logs:
            self.pay(CODES[0], 53.5)
        self.assertIn('Oversold', logs.output[0])
        self.assertEqual(Order.objects.get().status, Order.Status.CONFIRMED)
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 0)

    def test_payment_whose_checkout_is_gone_is_flagged_for_refund(self, viva, get_txn):
        self.guest_checkout()
        Checkout.objects.all().delete()
        get_txn.return_value = charged(CODES[0], 53.5)
        with self.assertLogs('payments.views', level='ERROR') as logs:
            self.pay(CODES[0], 53.5)
        self.assertIn('needs a refund', logs.output[0])
        self.assertFalse(Order.objects.exists())
        payment = Payment.objects.get()
        self.assertEqual((payment.status, payment.viva_transaction_id), (Payment.Status.REFUND_NEEDED, CHARGE))
        self.assertEqual(mail.outbox, [])  # no confirmation to the customer

        # Refunding it in Viva closes it; there's no order to cancel.
        get_txn.return_value = {'orderCode': int(CODES[0]), 'statusId': 'F', 'amount': -53.5, 'transactionTypeId': 4}
        self.client.post(WEBHOOK, payment_event(CODES[0], REFUND, event_type=1797), format='json')
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)

    def test_full_refund_cancels_the_new_order_and_gives_stock_back(self, viva, get_txn):
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        get_txn.return_value = {'orderCode': int(CODES[0]), 'statusId': 'F', 'amount': -53.5, 'transactionTypeId': 4}
        self.client.post(WEBHOOK, payment_event(CODES[0], REFUND, event_type=1797), format='json')
        self.assertEqual(Order.objects.get().status, Order.Status.CANCELLED)
        self.assertEqual(Payment.objects.get().status, Payment.Status.REFUNDED)
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 3)

    def test_two_checkouts_paid_are_two_orders(self, viva, get_txn):
        """Customer placed it twice and paid both: both are real paid orders for staff to see."""
        self.guest_checkout()
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        get_txn.return_value = charged(CODES[1], 53.5)
        self.pay(CODES[1], 53.5, transaction_id='44444444-4444-4444-8444-444444444444')
        self.assertEqual(Order.objects.filter(status=Order.Status.CONFIRMED).count(), 2)
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 1)

    def test_staff_cancelling_the_new_order_flags_the_refund(self, viva, get_txn):
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        order = Order.objects.get()
        staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.client.force_authenticate(user=staff)
        with self.assertLogs('orders.status', level='WARNING'):
            res = self.client.patch(f'/api/orders/admin/{order.pk}/', {'status': 'cancelled'}, format='json')
        self.assertTrue(res.data['refund_needed'])
        self.assertEqual(Payment.objects.get().status, Payment.Status.REFUND_NEEDED)
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 3)

    def test_customer_is_emailed_once_when_the_order_ships(self, viva, get_txn):
        data = self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        order = Order.objects.get()
        mail.outbox.clear()
        staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.client.force_authenticate(user=staff)

        def set_status(value):
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.patch(f'/api/orders/admin/{order.pk}/', {'status': value}, format='json')
            self.assertEqual(res.status_code, status.HTTP_200_OK)

        set_status('confirmed')  # unchanged: nothing sent
        self.assertEqual(mail.outbox, [])
        set_status('shipped')
        self.assertEqual(len(mail.outbox), 1)
        shipped = mail.outbox[0]
        self.assertEqual(shipped.to, ['guest@example.com'])
        self.assertEqual(shipped.subject, f'Your Senario order #{order.pk} is on its way')
        for text in ('on its way to you with ACS Courier', '1 x Hoodie (M)', 'Addr 1',
                     f"https://shop.example/order?id={order.pk}#t={data['token']}",
                     'Email us at Senarioproject@gmail.com.'):
            self.assertIn(text, shipped.body)
        self.assertIn('Hey Guest,', shipped.alternatives[0][0])

        set_status('shipped')    # saved again: no second email
        set_status('delivered')  # not a shipping email either
        self.assertEqual(len(mail.outbox), 1)

    def test_django_admin_shipping_emails_the_customer_too(self, viva, get_txn):
        from django.contrib import admin as django_admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from orders.admin import OrderAdmin
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        self.pay(CODES[0], 53.5)
        mail.outbox.clear()
        order = Order.objects.get()
        request = RequestFactory().post('/admin/')
        request.session = {}
        request._messages = FallbackStorage(request)
        order.status = Order.Status.SHIPPED
        with self.captureOnCommitCallbacks(execute=True):
            OrderAdmin(Order, django_admin.site).save_model(request, order, None, True)
        self.assertEqual([m.subject for m in mail.outbox], [f'Your Senario order #{order.pk} is on its way'])

    def test_a_shop_alert_failure_does_not_lose_the_order(self, viva, get_txn):
        self.guest_checkout()
        get_txn.return_value = charged(CODES[0], 53.5)
        real_send = __import__('users.emails', fromlist=['send_branded_email']).send_branded_email

        def alert_fails(to, subject, *args, **kwargs):
            if subject.startswith('New order'):
                raise RuntimeError('mail down')
            return real_send(to, subject, *args, **kwargs)

        with patch('orders.emails.send_branded_email', side_effect=alert_fails):
            with self.assertLogs('orders.emails', level='ERROR') as logs:
                self.pay(CODES[0], 53.5)
        self.assertIn('new-order alert', logs.output[0])
        self.assertEqual(Order.objects.get().status, Order.Status.CONFIRMED)
        self.assertEqual([m.to for m in mail.outbox], [['guest@example.com']])  # customer still emailed
