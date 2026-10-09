from django.core.cache import cache
from django_redis import get_redis_connection
from rest_framework.test import APITestCase

from .models import Category, Product


class ProductListCacheTests(APITestCase):
    def setUp(self):
        cache.clear()
        shirts = Category.objects.create(name='Shirts', slug='shirts')
        Product.objects.create(category=shirts, name='Tee', slug='tee', price='20.00')

    def tearDown(self):
        cache.clear()

    def product_cache_keys(self):
        return get_redis_connection('default').keys('*products:*')

    def test_junk_query_params_share_one_cache_entry(self):
        """Arbitrary params used to each create their own cache entry,
        letting anyone fill Redis with one request per made-up URL."""
        for i in range(5):
            res = self.client.get(f'/api/products/?junk={i}')
            self.assertEqual(len(res.data), 1)
        self.assertEqual(len(self.product_cache_keys()), 1)

    def test_searches_and_unknown_categories_are_not_cached(self):
        for i in range(3):
            self.client.get(f'/api/products/?search=tee{i}')
            self.client.get(f'/api/products/?category=nope{i}')
        self.assertEqual(self.product_cache_keys(), [])

    def test_category_filter_is_cached_separately(self):
        self.assertEqual(len(self.client.get('/api/products/?category=shirts').data), 1)
        self.assertEqual(len(self.client.get('/api/products/').data), 1)
        self.assertEqual(len(self.product_cache_keys()), 2)
