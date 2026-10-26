from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from products.models import Product, ProductVariant


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


