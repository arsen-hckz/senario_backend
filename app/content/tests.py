from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PageText
from .pages import CONCEPT

User = get_user_model()
DEFAULTS = {key: default for key, _label, default, _max, _multi in CONCEPT}


class PageTextTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.customer = User.objects.create_user(email='c@example.com', password='x')

    def test_public_page_shows_defaults_then_edits(self):
        self.assertEqual(self.client.get('/api/content/concept/').data, DEFAULTS)
        self.client.force_authenticate(self.staff)
        res = self.client.patch(
            '/api/content/admin/concept/',
            {'quote': 'Line one\r\nLine two  ', 'process_1': '  01 —   Cut \n'}, format='json',
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.client.force_authenticate(None)
        data = self.client.get('/api/content/concept/').data
        self.assertEqual(data['quote'], 'Line one\nLine two')
        self.assertEqual(data['process_1'], '01 — Cut')  # single-line fields lose line breaks
        self.assertEqual(data['hero_eyebrow'], DEFAULTS['hero_eyebrow'])

    def test_blank_or_default_text_goes_back_to_the_default(self):
        PageText.objects.create(page='concept', key='quote', value='x')
        PageText.objects.create(page='concept', key='quote_attr', value='y')
        self.client.force_authenticate(self.staff)
        self.client.patch('/api/content/admin/concept/', {'quote': '  ', 'quote_attr': DEFAULTS['quote_attr']}, format='json')
        self.assertFalse(PageText.objects.exists())

    def test_admin_form_lists_every_field_in_page_order(self):
        self.client.force_authenticate(self.staff)
        res = self.client.get('/api/content/admin/concept/')
        self.assertEqual([f['key'] for f in res.data], [f[0] for f in CONCEPT])
        self.assertEqual(set(res.data[0]), {'key', 'label', 'value', 'default', 'max_length', 'multiline'})

    def test_bad_input_is_a_400_and_saves_nothing(self):
        self.client.force_authenticate(self.staff)
        for body in ({'nope': 'x'}, {'quote': 5}, {'quote': ['a']}, {'quote': None}, {'quote': 'a\x00b'},
                     {'process_1': 'x' * 81}, {'quote': 'ok', 'pillar_1_title': {'a': 1}}):
            res = self.client.patch('/api/content/admin/concept/', body, format='json')
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, body)
        res = self.client.patch('/api/content/admin/concept/', ['a'], format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PageText.objects.exists())

    def test_unknown_page_is_404(self):
        self.assertEqual(self.client.get('/api/content/nope/').status_code, status.HTTP_404_NOT_FOUND)
        self.client.force_authenticate(self.staff)
        res = self.client.patch('/api/content/admin/nope/', {}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_editing_is_staff_only(self):
        res = self.client.patch('/api/content/admin/concept/', {'quote': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.force_authenticate(self.customer)
        res = self.client.patch('/api/content/admin/concept/', {'quote': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get('/api/content/admin/concept/').status_code, status.HTTP_403_FORBIDDEN)
