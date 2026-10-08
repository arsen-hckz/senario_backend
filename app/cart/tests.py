from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from products.models import Product, ProductVariant
from .models import CartItem

User = get_user_model()


class CartQtyTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='buyer@example.com', password='testpass123')
        self.client.force_authenticate(user=self.user)
        self.product = Product.objects.create(name='Tee', slug='tee', price=Decimal('20.00'), stock=5)
        self.variant = ProductVariant.objects.create(product=self.product, size='M', stock=2)

    def add(self, qty, variant=None):
        data = {'product_id': self.product.id, 'qty': qty}
        if variant:
            data['variant_id'] = variant.id
        return self.client.post('/api/cart/', data, format='json')

    def test_add_valid_qty(self):
        res = self.add(2)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(CartItem.objects.get().qty, 2)

    def test_add_rejects_non_numeric_negative_zero_and_huge_qty(self):
        for bad in ('abc', -3, 0, 100, None):
            res = self.add(bad)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, bad)
        self.assertFalse(CartItem.objects.exists())

    def test_add_rejects_more_than_stock_including_existing_qty(self):
        self.assertEqual(self.add(1, self.variant).status_code, status.HTTP_200_OK)
        res = self.add(2, self.variant)  # 1 + 2 > variant stock of 2
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CartItem.objects.get().qty, 1)

    def test_patch_validates_qty(self):
        self.add(1)
        item = CartItem.objects.get()
        url = f'/api/cart/{item.id}/'
        self.assertEqual(self.client.patch(url, {'qty': 'x'}, format='json').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.patch(url, {'qty': 6}, format='json').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.client.patch(url, {'qty': 3}, format='json').status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.qty, 3)
        self.assertEqual(self.client.patch(url, {'qty': 0}, format='json').status_code, status.HTTP_200_OK)
        self.assertFalse(CartItem.objects.exists())
