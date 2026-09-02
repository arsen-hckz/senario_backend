from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase

from .tokens import email_verification_token

User = get_user_model()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailVerificationTests(APITestCase):
    def register(self, email='new@example.com'):
        return self.client.post('/api/auth/register/', {
            'email': email,
            'password': 'testpass123',
            'first_name': 'Test',
        }, format='json')

    def test_register_creates_unverified_user_and_sends_email(self):
        res = self.register()
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertNotIn('access', res.data)

        user = User.objects.get(email='new@example.com')
        self.assertFalse(user.is_email_verified)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(user.email, mail.outbox[0].to)

    def test_login_rejected_before_verification(self):
        self.register()
        res = self.client.post('/api/auth/login/', {
            'email': 'new@example.com',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_verify_email_activates_account_and_allows_login(self):
        self.register()
        user = User.objects.get(email='new@example.com')
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)

        res = self.client.get(f'/api/auth/verify-email/{uid}/{token}/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        user.refresh_from_db()
        self.assertTrue(user.is_email_verified)

        login = self.client.post('/api/auth/login/', {
            'email': 'new@example.com',
            'password': 'testpass123',
        }, format='json')
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertIn('access', login.data)

    def test_verify_email_rejects_bad_token(self):
        self.register()
        user = User.objects.get(email='new@example.com')
        uid = urlsafe_base64_encode(force_bytes(user.pk))

        res = self.client.get(f'/api/auth/verify-email/{uid}/not-a-real-token/')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

        user.refresh_from_db()
        self.assertFalse(user.is_email_verified)

    def test_verify_email_token_is_single_use(self):
        self.register()
        user = User.objects.get(email='new@example.com')
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = email_verification_token.make_token(user)

        first = self.client.get(f'/api/auth/verify-email/{uid}/{token}/')
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.get(f'/api/auth/verify-email/{uid}/{token}/')
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_resend_verification_is_generic_for_unknown_email(self):
        res = self.client.post('/api/auth/resend-verification/', {
            'email': 'nobody@example.com',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_verification_sends_for_unverified_user(self):
        self.register()
        mail.outbox.clear()

        res = self.client.post('/api/auth/resend-verification/', {
            'email': 'new@example.com',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_verification_skips_already_verified_user(self):
        self.register()
        user = User.objects.get(email='new@example.com')
        user.is_email_verified = True
        user.save(update_fields=['is_email_verified'])
        mail.outbox.clear()

        res = self.client.post('/api/auth/resend-verification/', {
            'email': 'new@example.com',
        }, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)
