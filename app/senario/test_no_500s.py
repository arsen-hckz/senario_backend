"""Every API endpoint answers junk with a 4xx, never a 500 (each 500 emails staff)."""
import re
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APITestCase

from orders.models import Order
from products.models import Product

User = get_user_model()

JUNK_JSON = [
    '[]', '[1, 2]', '"text"', '123', 'null', 'true', '{', '',
    '{"items": [{"product_id": 1e400, "qty": 1}]}',
    '{"items": [{"product_id": 1, "qty": 1e400}]}',
    '{"product_id": 1e400}', '{"qty": 1e400}', '{"item_id": -1e400}', '{"order": [1e400]}',
    '{"x": NaN}', '{"x": Infinity}',
    '{"product_id": 99999999999999999999999, "qty": 1}', '{"qty": 99999999999999999999999}',
    '{"email": ["a"], "password": {"x": 1}, "refresh": [1], "token": {"a": 1}}',
    '{"email": "a\\u0000b@example.com", "password": "x\\u0000"}',
    '{"refresh": {"a": 1}}', '{"items": "x"}', '{"items": [1, "a", null, []]}',
    '{"order": "x"}', '{"order": {"a": 1}}', '{"EventTypeId": [1796], "EventData": "x"}',
    '{"status": ["confirmed"]}', '{"sizes": "x"}', '{"sizes": [{"size": ["S"], "stock": 1e400}]}',
]


def _urls(patterns, prefix=''):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _urls(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern)


def _concrete(route, obj_id):
    route = re.sub(r'<int:\w+>', str(obj_id), route)
    route = re.sub(r'<slug:\w+>', 'concept', route)
    route = re.sub(r'<(str:)?\w+>', 'x', route)
    return '/' + route.replace('^', '').replace('$', '')


class NoServerErrorsTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.customer = User.objects.create_user(email='c@example.com', password='x')
        self.product = Product.objects.create(name='Tee', slug='tee', price=Decimal('10'), stock=5)
        self.order = Order.objects.create(user=self.customer, total=Decimal('10'), full_name='A', address='B',
                                          city='C', country='GR', postal_code='1')

    def tearDown(self):
        cache.clear()

    @patch('payments.viva_client.get_transaction', return_value={})
    @patch('payments.viva_client.create_order', return_value='1234567890123456')
    def test_junk_bodies_never_cause_a_500(self, _create, _get):
        routes = sorted({r for r in _urls(get_resolver().url_patterns) if r.startswith('api/')})
        self.assertGreater(len(routes), 20)
        failures = []
        for who in (None, self.customer, self.staff):
            self.client.force_authenticate(who)
            for route in routes:
                url = _concrete(route, self.order.id)
                for method in ('post', 'patch', 'put', 'delete'):
                    for body in JUNK_JSON:
                        cache.clear()  # keep throttles from hiding a crash behind a 429
                        res = self.client.generic(method.upper(), url, body, content_type='application/json')
                        if res.status_code >= 500:
                            failures.append(f'{method.upper()} {url} {body[:40]} as {who} -> {res.status_code}')
        self.maxDiff = None
        self.assertEqual(failures, [])

    def test_non_object_or_infinite_json_is_a_400(self):
        for body in ('[]', '"x"', '{"items": [{"product_id": 1e400, "qty": 1}]}'):
            res = self.client.generic('POST', '/api/cart/quote/', body, content_type='application/json')
            self.assertEqual(res.status_code, 400, body)
        res = self.client.generic('POST', '/api/auth/logout/', '[]', content_type='application/json')
        self.assertEqual(res.status_code, 400)
