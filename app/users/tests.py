from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PendingRegistration

User = get_user_model()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailVerificationTests(APITestCase):
    def register(self, email='new@example.com', password='testpass123'):
        return self.client.post('/api/auth/register/', {
            'email': email,
            'password': password,
            'first_name': 'Test',
        }, format='json')

    def test_register_creates_pending_registration_not_user(self):
        res = self.register()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        self.assertFalse(User.objects.filter(email='new@example.com').exists())
        self.assertTrue(PendingRegistration.objects.filter(email='new@example.com').exists())

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('new@example.com', mail.outbox[0].to)

    def test_register_retry_with_same_pending_email_succeeds_and_refreshes_token(self):
        """The bug this fixes: registering again with an email that was never
        verified must succeed (and just issue a fresh link), not 400."""
        first = self.register(password='firstpass123')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        first_token = PendingRegistration.objects.get(email='new@example.com').token

        second = self.register(password='secondpass123')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        self.assertEqual(PendingRegistration.objects.filter(email='new@example.com').count(), 1)
        pending = PendingRegistration.objects.get(email='new@example.com')
        self.assertNotEqual(pending.token, first_token)
        self.assertEqual(len(mail.outbox), 2)

    def test_register_rejects_email_of_already_verified_user(self):
        self.register()
        pending = PendingRegistration.objects.get(email='new@example.com')
        self.client.get(f'/api/auth/verify-email/{pending.token}/')

        res = self.register()
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_before_verification_gives_helpful_message(self):
        self.register()
        res = self.client.post('/api/auth/login/', {
            'email': 'new@example.com',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('verify', res.data['detail'].lower())

    def test_login_with_unregistered_email_gives_generic_message(self):
        res = self.client.post('/api/auth/login/', {
            'email': 'nobody@example.com',
            'password': 'whatever123',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn('verify', res.data['detail'].lower())

    def test_verify_email_creates_user_deletes_pending_and_allows_login(self):
        self.register()
        pending = PendingRegistration.objects.get(email='new@example.com')

        res = self.client.get(f'/api/auth/verify-email/{pending.token}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.assertFalse(PendingRegistration.objects.filter(email='new@example.com').exists())
        user = User.objects.get(email='new@example.com')
        self.assertEqual(user.first_name, 'Test')

        login = self.client.post('/api/auth/login/', {
            'email': 'new@example.com',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn('access', login.data)

    def test_verify_email_rejects_bad_token(self):
        res = self.client.get('/api/auth/verify-email/not-a-real-token/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_email_rejects_expired_token(self):
        self.register()
        pending = PendingRegistration.objects.get(email='new@example.com')
        pending.created_at = timezone.now() - timedelta(days=30)
        pending.save(update_fields=['created_at'])

        res = self.client.get(f'/api/auth/verify-email/{pending.token}/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(email='new@example.com').exists())

    def test_verify_email_token_is_single_use(self):
        self.register()
        pending = PendingRegistration.objects.get(email='new@example.com')
        token = pending.token

        first = self.client.get(f'/api/auth/verify-email/{token}/')
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.get(f'/api/auth/verify-email/{token}/')
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resend_verification_is_generic_for_unknown_email(self):
        res = self.client.post('/api/auth/resend-verification/', {
            'email': 'nobody@example.com',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_verification_regenerates_token_and_sends(self):
        self.register()
        old_token = PendingRegistration.objects.get(email='new@example.com').token
        mail.outbox.clear()

        res = self.client.post('/api/auth/resend-verification/', {
            'email': 'new@example.com',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

        new_token = PendingRegistration.objects.get(email='new@example.com').token
        self.assertNotEqual(old_token, new_token)

        # old link must no longer work
        stale = self.client.get(f'/api/auth/verify-email/{old_token}/')
        self.assertEqual(stale.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resend_verification_noop_for_already_verified_email(self):
        self.register()
        pending = PendingRegistration.objects.get(email='new@example.com')
        self.client.get(f'/api/auth/verify-email/{pending.token}/')
        mail.outbox.clear()

        res = self.client.post('/api/auth/resend-verification/', {
            'email': 'new@example.com',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)
