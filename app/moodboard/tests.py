import io
import os
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from .models import MoodboardPhoto

User = get_user_model()


def make_png(name):
    buf = io.BytesIO()
    Image.new('RGB', (10, 10)).save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class MoodboardTests(APITestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            email='staff@example.com', password='testpass123',
            is_staff=True,
        )
        self.customer = User.objects.create_user(
            email='customer@example.com', password='testpass123',
        )

    def auth(self, user):
        self.client.force_authenticate(user=user)

    def test_public_list_requires_no_auth_and_is_ordered(self):
        MoodboardPhoto.objects.create(title='Second', external_src='b.jpg', order=1)
        MoodboardPhoto.objects.create(title='First', external_src='a.jpg', order=0)

        res = self.client.get('/api/moodboard/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual([p['title'] for p in res.data], ['First', 'Second'])
        self.assertEqual(res.data[0]['src'], 'a.jpg')

    def test_create_requires_staff(self):
        self.auth(self.customer)
        res = self.client.post('/api/moodboard/admin/', {'title': 'T', 'body': 'b', 'src': 'x.jpg'})
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_assigns_incrementing_order(self):
        self.auth(self.staff)
        r1 = self.client.post('/api/moodboard/admin/', {'title': 'T1', 'body': 'b1', 'src': 'a.jpg'})
        r2 = self.client.post('/api/moodboard/admin/', {'title': 'T2', 'body': 'b2', 'src': 'b.jpg'})
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r1.data['order'], 0)
        self.assertEqual(r2.data['order'], 1)
        self.assertEqual(r2.data['src'], 'b.jpg')

    def test_partial_update_only_changes_given_fields(self):
        photo = MoodboardPhoto.objects.create(title='Orig', body='orig body', external_src='a.jpg', order=0)
        self.auth(self.staff)

        res = self.client.patch(f'/api/moodboard/admin/{photo.id}/', {'title': 'New title'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        photo.refresh_from_db()
        self.assertEqual(photo.title, 'New title')
        self.assertEqual(photo.body, 'orig body')
        self.assertEqual(photo.external_src, 'a.jpg')

    def test_delete_requires_staff_and_removes_photo(self):
        photo = MoodboardPhoto.objects.create(title='Gone', external_src='a.jpg', order=0)

        self.auth(self.customer)
        forbidden = self.client.delete(f'/api/moodboard/admin/{photo.id}/')
        self.assertEqual(forbidden.status_code, status.HTTP_403_FORBIDDEN)

        self.auth(self.staff)
        res = self.client.delete(f'/api/moodboard/admin/{photo.id}/')
        self.assertIn(res.status_code, (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT))
        self.assertFalse(MoodboardPhoto.objects.filter(id=photo.id).exists())

    def test_uploads_are_downsized(self):
        buf = io.BytesIO()
        Image.new('RGB', (4000, 3000), (200, 80, 40)).save(buf, format='JPEG', quality=100)
        self.auth(self.staff)
        res = self.client.post('/api/moodboard/admin/', {
            'title': 'Big', 'image': SimpleUploadedFile('IMG_1.jpeg', buf.getvalue(), content_type='image/jpeg'),
        }, format='multipart')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.data)
        with Image.open(MoodboardPhoto.objects.get(pk=res.data['id']).image.path) as stored:
            self.assertEqual(max(stored.size), 2000)

    def big_jpeg(self, name='IMG_1.jpeg'):
        buf = io.BytesIO()
        Image.new('RGB', (4000, 3000), (200, 80, 40)).save(buf, format='JPEG', quality=100)
        return SimpleUploadedFile(name, buf.getvalue(), content_type='image/jpeg')

    def test_upload_gets_a_grid_thumbnail_and_list_returns_both(self):
        self.auth(self.staff)
        res = self.client.post('/api/moodboard/admin/', {'title': 'Big', 'image': self.big_jpeg()}, format='multipart')
        photo = MoodboardPhoto.objects.get(pk=res.data['id'])
        with Image.open(photo.thumb.path) as thumb:
            self.assertEqual(max(thumb.size), 1000)

        item = self.client.get('/api/moodboard/').data[0]
        self.assertTrue(item['src'].endswith(photo.image.name))
        self.assertTrue(item['thumb'].endswith(photo.thumb.name))
        self.assertNotEqual(item['src'], item['thumb'])

    def test_external_src_photo_uses_src_as_thumb(self):
        MoodboardPhoto.objects.create(title='Ext', external_src='a.jpg')
        item = self.client.get('/api/moodboard/').data[0]
        self.assertEqual(item['thumb'], 'a.jpg')

    def test_replacing_image_replaces_thumbnail_and_delete_removes_it(self):
        self.auth(self.staff)
        res = self.client.post('/api/moodboard/admin/', {'title': 'T', 'image': make_png('one.png')}, format='multipart')
        photo = MoodboardPhoto.objects.get(pk=res.data['id'])
        old_thumb = photo.thumb.path

        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f'/api/moodboard/admin/{photo.id}/', {'image': make_png('two.png')}, format='multipart')
        photo.refresh_from_db()
        self.assertFalse(os.path.exists(old_thumb))
        self.assertTrue(os.path.exists(photo.thumb.path))
        self.assertIn('two', photo.thumb.name)

        new_thumb = photo.thumb.path
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f'/api/moodboard/admin/{photo.id}/')
        self.assertFalse(os.path.exists(new_thumb))

    def test_backfill_migration_creates_missing_thumbnails(self):
        import importlib
        from django.apps import apps
        self.auth(self.staff)
        res = self.client.post('/api/moodboard/admin/', {'title': 'Old', 'image': self.big_jpeg()}, format='multipart')
        # Production's real starting state: the new column is NULL on old rows.
        MoodboardPhoto.objects.filter(pk=res.data['id']).update(thumb=None)
        MoodboardPhoto.objects.create(title='Missing file', image='moodboard/gone.jpg')
        MoodboardPhoto.objects.filter(title='Missing file').update(thumb=None)

        migration = importlib.import_module('moodboard.migrations.0004_backfill_thumbnails_null')
        migration.backfill_thumbnails(apps, None)

        photo = MoodboardPhoto.objects.get(pk=res.data['id'])
        with Image.open(photo.thumb.path) as thumb:
            self.assertEqual(max(thumb.size), 1000)
        self.assertFalse(MoodboardPhoto.objects.get(title='Missing file').thumb)

    def test_replacing_or_deleting_an_upload_deletes_the_old_file(self):
        self.auth(self.staff)
        res = self.client.post('/api/moodboard/admin/', {'title': 'T', 'image': make_png('one.png')}, format='multipart')
        photo = MoodboardPhoto.objects.get(pk=res.data['id'])
        first_path = photo.image.path

        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(f'/api/moodboard/admin/{photo.id}/', {'image': make_png('two.png')}, format='multipart')
        photo.refresh_from_db()
        self.assertFalse(os.path.exists(first_path))
        second_path = photo.image.path
        self.assertTrue(os.path.exists(second_path))

        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(f'/api/moodboard/admin/{photo.id}/')
        self.assertFalse(os.path.exists(second_path))

    def test_reorder_updates_order_to_match_index(self):
        p1 = MoodboardPhoto.objects.create(title='A', external_src='a.jpg', order=0)
        p2 = MoodboardPhoto.objects.create(title='B', external_src='b.jpg', order=1)
        p3 = MoodboardPhoto.objects.create(title='C', external_src='c.jpg', order=2)

        self.auth(self.staff)
        res = self.client.post('/api/moodboard/admin/reorder/', {'order': [p3.id, p1.id, p2.id]}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        p1.refresh_from_db()
        p2.refresh_from_db()
        p3.refresh_from_db()
        self.assertEqual(p3.order, 0)
        self.assertEqual(p1.order, 1)
        self.assertEqual(p2.order, 2)

    def test_reorder_requires_staff(self):
        self.auth(self.customer)
        res = self.client.post('/api/moodboard/admin/reorder/', {'order': []}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
