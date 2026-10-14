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
    'country': 'GR', 'postal_code': '11111', 'phone': '+30 690 000 0000',
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

    def test_phone_is_required_and_email_defaults_to_account(self):
        res = self.client.post('/api/orders/create/', dict(ADDRESS, phone=''), format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('phone', res.data)
        res = self.client.post('/api/orders/create/', dict(ADDRESS, phone='call me'), format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual((res.data['email'], res.data['phone']), ('buyer@example.com', '+30 690 000 0000'))

    def test_checkout_email_overrides_account_email(self):
        res = self.client.post('/api/orders/create/', dict(ADDRESS, email='gift@example.com'), format='json')
        self.assertEqual(Order.objects.get(pk=res.data['id']).email, 'gift@example.com')

    def test_sized_item_without_size_cannot_be_ordered(self):
        from products.models import ProductVariant
        ProductVariant.objects.create(product=self.product, size='M', stock=5)
        res = self.create()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Please choose a size for: Tee', str(res.data))
        self.assertFalse(Order.objects.exists())

        cart = self.client.get('/api/cart/').data
        self.assertTrue(cart['items'][0]['needs_size'])

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
