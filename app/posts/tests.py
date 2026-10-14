from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from products.models import Product
from .models import SalePost

User = get_user_model()


class SalePostTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.customer = User.objects.create_user(email='c@example.com', password='x')
        self.tee = Product.objects.create(name='Tee', slug='tee', price=Decimal('20'))
        self.cap = Product.objects.create(name='Cap', slug='cap', price=Decimal('10'))

    def test_staff_create_assigns_next_order_and_public_list_shows_it(self):
        self.client.force_authenticate(self.staff)
        first = self.client.post('/api/posts/admin/', {'product_slug': 'tee', 'headline': 'Hot'}, format='json')
        second = self.client.post('/api/posts/admin/', {'product_slug': 'cap', 'headline': 'Cool', 'note': 'n'}, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual((first.data['order'], second.data['order']), (0, 1))

        self.client.force_authenticate(None)
        res = self.client.get('/api/posts/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([p['product_slug'] for p in res.data], ['tee', 'cap'])
        self.assertEqual(set(res.data[0]), {'id', 'product_slug', 'headline', 'note', 'order'})

    def test_unknown_product_slug_is_a_400(self):
        self.client.force_authenticate(self.staff)
        res = self.client.post('/api/posts/admin/', {'product_slug': 'nope', 'headline': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_customers_cannot_write(self):
        self.client.force_authenticate(self.customer)
        res = self.client.post('/api/posts/admin/', {'product_slug': 'tee', 'headline': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_reorder_patch_delete(self):
        a = SalePost.objects.create(product=self.tee, headline='a', order=0)
        b = SalePost.objects.create(product=self.cap, headline='b', order=1)
        self.client.force_authenticate(self.staff)
        res = self.client.post('/api/posts/admin/reorder/', {'order': [b.id, a.id]}, format='json')
        self.assertEqual([p['id'] for p in res.data], [b.id, a.id])
        res = self.client.patch(f'/api/posts/admin/{a.id}/', {'headline': 'new'}, format='json')
        self.assertEqual(res.data['headline'], 'new')
        res = self.client.delete(f'/api/posts/admin/{a.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)

    def test_hidden_products_posts_are_not_public(self):
        SalePost.objects.create(product=self.tee, headline='a')
        self.tee.is_active = False
        self.tee.save()
        self.assertEqual(self.client.get('/api/posts/').data, [])
