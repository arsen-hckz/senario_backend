from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Product

User = get_user_model()


class ProductOrderTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.customer = User.objects.create_user(email='c@example.com', password='x')
        self.a = Product.objects.create(name='A', slug='a', price='10.00', position=0)
        self.b = Product.objects.create(name='B', slug='b', price='10.00', position=1)
        self.c = Product.objects.create(name='C', slug='c', price='10.00', position=2)

    def tearDown(self):
        cache.clear()

    def slugs(self):
        return [p['slug'] for p in self.client.get('/api/products/').data]

    def test_reorder_sets_the_shop_order_and_clears_the_cache(self):
        self.assertEqual(self.slugs(), ['a', 'b', 'c'])  # now cached
        self.client.force_authenticate(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post('/api/products/admin/reorder/', {'order': [self.c.id, self.a.id, self.b.id]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([p['slug'] for p in res.data], ['c', 'a', 'b'])
        self.client.force_authenticate(None)
        self.assertEqual(self.slugs(), ['c', 'a', 'b'])

    def test_partial_or_junk_list_keeps_the_rest_in_order(self):
        self.client.force_authenticate(self.staff)
        res = self.client.post(
            '/api/products/admin/reorder/',
            {'order': ['junk', None, {'x': 1}, 1.5, True, str(self.c.id), self.c.id, 99999]}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([p['slug'] for p in res.data], ['c', 'a', 'b'])
        self.assertEqual([p['position'] for p in res.data], [0, 1, 2])

    def test_reorder_rejects_non_lists(self):
        self.client.force_authenticate(self.staff)
        for body in ({'order': 'abc'}, {'order': {'1': 2}}, {}, {'order': list(range(1001))}):
            res = self.client.post('/api/products/admin/reorder/', body, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, body)

    def test_reorder_is_staff_only(self):
        res = self.client.post('/api/products/admin/reorder/', {'order': []}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.force_authenticate(self.customer)
        res = self.client.post('/api/products/admin/reorder/', {'order': []}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_new_product_goes_last_and_position_is_read_only(self):
        self.client.force_authenticate(self.staff)
        res = self.client.post('/api/products/admin/', {'name': 'D', 'price': '5', 'position': 0}, format='json')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        self.assertEqual(res.data['position'], 3)
        res = self.client.patch(f'/api/products/admin/{self.c.id}/', {'position': 0}, format='json')
        self.assertEqual(res.data['position'], 2)
