from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from .models import MoodboardPhoto

User = get_user_model()


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
