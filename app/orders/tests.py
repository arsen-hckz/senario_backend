from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from cart.models import Cart, CartItem
from products.models import Product
from .models import Order, OrderItem

User = get_user_model()

ADDRESS = {
    'full_name': 'Buyer Name', 'address': 'Addr 1', 'city': 'Athens',
    'country': 'GR', 'postal_code': '11111',
}


class CreateOrderTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email='buyer@example.com', password='testpass123')
        self.client.force_authenticate(user=self.user)
        self.product = Product.objects.create(
            name='Tee', slug='tee', price=Decimal('20.00'), sale_price=Decimal('15.00'), stock=5,
        )
        self.cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=self.cart, product=self.product, qty=2)

    def create(self):
        return self.client.post('/api/orders/create/', ADDRESS, format='json')

    def test_creates_order_with_server_side_total_and_empties_cart(self):
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        order = Order.objects.get()
        self.assertEqual(order.total, Decimal('30.00'))
        self.assertEqual(order.items.get().price, Decimal('15.00'))
        self.assertFalse(self.cart.items.exists())

    def test_rejects_when_stock_ran_out(self):
        self.product.stock = 1
        self.product.save()
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Order.objects.exists())
        self.assertTrue(self.cart.items.exists())

    def test_rejects_deactivated_product(self):
        self.product.is_active = False
        self.product.save()
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(Order.objects.exists())

    def test_failure_midway_leaves_no_partial_order_and_keeps_cart(self):
        with patch.object(OrderItem.objects, 'bulk_create', side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.create()
        self.assertFalse(Order.objects.exists())
        self.assertTrue(self.cart.items.exists())
