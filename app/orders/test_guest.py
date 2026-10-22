from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from payments.models import Payment
from products.models import Product, ProductVariant
from users.models import User
from .models import Order

ADDRESS = {
    'full_name': 'Guest Buyer', 'email': 'guest@example.com', 'phone': '+30 690 000 0000',
    'address': 'Addr 1', 'city': 'Athens', 'country': 'Greece', 'postal_code': '11111',
}
TXN = '11111111-1111-4111-8111-111111111111'


@override_settings(SHIPPING_FEE='3.50', FREE_SHIPPING_OVER='50')
class GuestCartQuoteTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.tee = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), sale_price=Decimal('15.00'), stock=5)
        self.hoodie = Product.objects.create(name='Hoodie', slug='hoodie', price=Decimal('50.00'), stock=0)
        self.m = ProductVariant.objects.create(product=self.hoodie, size='M', stock=1)

    def quote(self, items):
        return self.client.post('/api/cart/quote/', {'items': items}, format='json')

    def test_prices_come_from_the_database_with_shipping(self):
        res = self.quote([{'product_id': self.tee.id, 'qty': 2, 'price': '0.01'}])
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual((res.data['total'], res.data['shipping'], res.data['grand_total']), ('30.00', '3.50', '33.50'))
        self.assertEqual(res.data['items'][0]['id'], f'{self.tee.id}-0')
        self.assertEqual(res.data['item_count'], 2)

    def test_free_shipping_from_the_threshold(self):
        res = self.quote([{'product_id': self.hoodie.id, 'variant_id': self.m.id, 'qty': 1}])
        self.assertEqual((res.data['shipping'], res.data['grand_total']), ('0.00', '50.00'))

    @override_settings(FREE_SHIPPING_OVER='')
    def test_shipping_is_always_charged_without_a_threshold(self):
        res = self.quote([{'product_id': self.hoodie.id, 'variant_id': self.m.id, 'qty': 1}])
        self.assertEqual((res.data['shipping'], res.data['grand_total']), ('3.50', '53.50'))
        self.assertIsNone(self.client.get('/api/orders/shipping/').data['free_over'])

    def test_lines_that_cannot_be_bought_say_why(self):
        res = self.quote([
            {'product_id': self.hoodie.id, 'qty': 1},                         # no size
            {'product_id': self.hoodie.id, 'variant_id': self.m.id, 'qty': 3},  # only 1 left
        ])
        problems = [item['problem'] for item in res.data['items']]
        self.assertEqual(problems, ['Please choose a size.', 'Only 1 left in stock.'])
        self.assertTrue(res.data['items'][0]['needs_size'])

    def test_missing_or_hidden_products_are_dropped(self):
        Product.objects.filter(pk=self.tee.pk).update(is_active=False)
        other = ProductVariant.objects.create(product=Product.objects.create(name='X', slug='x', price=1), size='S', stock=1)
        res = self.quote([
            {'product_id': self.tee.id, 'qty': 1},
            {'product_id': 999999, 'qty': 1},
            {'product_id': self.hoodie.id, 'variant_id': other.id, 'qty': 1},  # someone else's size
        ])
        self.assertEqual((res.data['items'], res.data['dropped']), ([], 3))

    def test_duplicates_merge_and_junk_is_a_400(self):
        res = self.quote([{'product_id': self.tee.id, 'qty': 2}, {'product_id': str(self.tee.id), 'qty': '1'}])
        self.assertEqual(res.data['items'][0]['qty'], 3)
        for junk in (None, 'x', [1], [{'product_id': self.tee.id, 'qty': 0}], [{'product_id': True}],
                     [{'product_id': self.tee.id, 'qty': 100}], [{'product_id': 1}] * 51):
            self.assertEqual(self.quote(junk).status_code, status.HTTP_400_BAD_REQUEST, junk)


@override_settings(SHIPPING_FEE='3.50', FREE_SHIPPING_OVER='50')
class GuestOrderTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.tee = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), stock=5)

    def place(self, items=None, **overrides):
        body = dict(ADDRESS, items=items if items is not None else [{'product_id': self.tee.id, 'qty': 2}], **overrides)
        return self.client.post('/api/orders/guest/', body, format='json')

    def detail(self, order_id, token):
        headers = {'HTTP_X_ORDER_TOKEN': token} if token is not None else {}
        return self.client.get(f'/api/orders/guest/{order_id}/', **headers)

    def test_places_an_order_without_an_account(self):
        res = self.place()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get()
        self.assertIsNone(order.user)
        self.assertEqual((order.total, order.shipping, order.email), (Decimal('43.50'), Decimal('3.50'), 'guest@example.com'))
        self.assertEqual(res.data['access_token'], order.access_token)
        self.assertGreaterEqual(len(order.access_token), 40)
        self.assertTrue(res.data['is_guest'])

    def test_email_is_required_and_bad_carts_are_refused(self):
        self.assertEqual(self.place(email='').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.place(items=[]).status_code, status.HTTP_400_BAD_REQUEST)
        res = self.place(items=[{'product_id': self.tee.id, 'qty': 6}])
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Only 5 left in stock', str(res.data))
        self.assertFalse(Order.objects.exists())

    def test_delivers_only_within_greece(self):
        res = self.place(country='Cyprus')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('only deliver within Greece', str(res.data))
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.place(country=' gr ').status_code, status.HTTP_201_CREATED)
        self.assertEqual(Order.objects.get().country, 'Greece')

    def test_order_opens_only_with_its_secret(self):
        token = self.place().data['access_token']
        order = Order.objects.get()
        self.assertEqual(self.detail(order.id, token).status_code, status.HTTP_200_OK)
        self.assertNotIn('access_token', self.detail(order.id, token).data)
        for wrong in (None, '', 'x' * 43, token[:-1]):
            self.assertEqual(self.detail(order.id, wrong).status_code, status.HTTP_404_NOT_FOUND, wrong)

    def test_account_orders_are_never_reachable_as_guest_orders(self):
        user = User.objects.create_user(email='a@example.com', password='Str0ng-Pass-123')
        order = Order.objects.create(user=user, total=10, full_name='A', address='a', city='c', country='g', postal_code='1')
        self.assertEqual(self.detail(order.id, '').status_code, status.HTTP_404_NOT_FOUND)
        res = self.client.post(f'/api/payments/guest-checkout/{order.id}/', HTTP_X_ORDER_TOKEN='')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @patch('payments.viva_client.create_order', return_value='123456789012345')
    def test_guest_checkout_charges_the_total_with_shipping(self, create_order):
        token = self.place().data['access_token']
        order = Order.objects.get()
        res = self.client.post(f'/api/payments/guest-checkout/{order.id}/', HTTP_X_ORDER_TOKEN='wrong')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        res = self.client.post(f'/api/payments/guest-checkout/{order.id}/', HTTP_X_ORDER_TOKEN=token)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('123456789012345', res.data['checkout_url'])
        kwargs = create_order.call_args.kwargs
        self.assertEqual((kwargs['amount_cents'], kwargs['customer_email']), (4350, 'guest@example.com'))

    @override_settings(FRONTEND_URL='https://shop.example')
    @patch('payments.viva_client.get_transaction')
    def test_paid_guest_order_is_confirmed_and_emailed_with_its_link(self, get_transaction):
        token = self.place().data['access_token']
        order = Order.objects.get()
        Payment.objects.create(order=order, viva_order_code='555', amount=order.total)
        get_transaction.return_value = {'statusId': 'F', 'orderCode': '555', 'amount': 43.5}
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post('/api/payments/webhook/viva/', {
                'EventTypeId': 1796, 'EventData': {'OrderCode': '555', 'TransactionId': TXN},
            }, format='json')
        order.refresh_from_db()
        self.tee.refresh_from_db()
        self.assertEqual((order.status, self.tee.stock), ('confirmed', 3))
        self.assertEqual(mail.outbox[-1].to, ['guest@example.com'])
        self.assertIn(f'https://shop.example/order?id={order.id}#t={token}', mail.outbox[-1].body)
        self.assertIn('Shipping  €3.50', mail.outbox[-1].body)

    def test_guest_orders_are_rate_limited_per_ip(self):
        codes = [self.place(items=[{'product_id': self.tee.id, 'qty': 1}]).status_code for _ in range(21)]
        self.assertEqual(codes[-1], status.HTTP_429_TOO_MANY_REQUESTS)
