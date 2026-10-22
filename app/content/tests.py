import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PageImage, PageText
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


def jpeg(size=(3000, 2000)):
    buf = io.BytesIO()
    Image.new('RGB', size, (200, 80, 40)).save(buf, format='JPEG')
    return SimpleUploadedFile('photo.jpg', buf.getvalue(), content_type='image/jpeg')


class PageImageTests(APITestCase):
    URL = '/api/content/admin/concept/images/'

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.staff = User.objects.create_user(email='staff@example.com', password='x', is_staff=True)
        self.customer = User.objects.create_user(email='c@example.com', password='x')

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def upload(self, key='process_photo_1', file=None):
        return self.client.post(f'{self.URL}{key}/', {'image': file or jpeg()}, format='multipart')

    def test_public_list_is_null_until_a_photo_is_uploaded(self):
        res = self.client.get('/api/content/concept/images/')
        self.assertEqual(res.data, {f'process_photo_{n}': None for n in range(1, 5)})

    def test_upload_replace_and_reset(self):
        self.client.force_authenticate(self.staff)
        res = self.upload()
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        first = PageImage.objects.get()
        self.assertLessEqual(max(Image.open(first.image.path).size), 2000)  # downsized on save
        self.assertTrue(res.data[0]['url'].endswith(first.image.url))

        self.client.force_authenticate(None)
        public = self.client.get('/api/content/concept/images/').data
        self.assertTrue(public['process_photo_1'].startswith('http://testserver/media/content/'))
        self.assertIsNone(public['process_photo_2'])

        self.client.force_authenticate(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            self.upload()
        second = PageImage.objects.get()
        self.assertNotEqual(first.image.name, second.image.name)
        self.assertFalse(first.image.storage.exists(first.image.name))  # old file removed

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.delete(f'{self.URL}process_photo_1/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertFalse(PageImage.objects.exists())
        self.assertFalse(second.image.storage.exists(second.image.name))

    def test_bad_uploads_are_a_400(self):
        self.client.force_authenticate(self.staff)
        not_image = SimpleUploadedFile('x.jpg', b'not an image', content_type='image/jpeg')
        self.assertEqual(self.upload(file=not_image).status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post(f'{self.URL}process_photo_1/', {}, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        res = self.client.post(f'{self.URL}process_photo_1/', {'image': 'x'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
        self.assertFalse(PageImage.objects.exists())

    def test_unknown_page_or_slot_is_404(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.upload(key='nope').status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get('/api/content/nope/images/').status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.post('/api/content/admin/nope/images/process_photo_1/',
                                          {'image': jpeg()}, format='multipart').status_code, status.HTTP_404_NOT_FOUND)

    def test_changing_photos_is_staff_only(self):
        self.assertEqual(self.upload().status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.upload().status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.delete(f'{self.URL}process_photo_1/').status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(self.URL).status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(PageImage.objects.exists())
