from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PendingRegistration

User = get_user_model()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class EmailVerificationTests(APITestCase):
    def setUp(self):
        # Rate-limit counters live in Redis and would otherwise carry over between tests.
        cache.clear()

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

    def test_register_retry_with_same_pending_email_succeeds_and_resends_link(self):
        """Registering again with an email that was never verified must
        succeed (and re-send the link), not 400."""
        first = self.register(password='firstpass123')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        first_token = PendingRegistration.objects.get(email='new@example.com').token

        second = self.register(password='secondpass123')
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        self.assertEqual(PendingRegistration.objects.filter(email='new@example.com').count(), 1)
        pending = PendingRegistration.objects.get(email='new@example.com')
        self.assertEqual(pending.token, first_token)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn(first_token, mail.outbox[1].body)

    def test_re_registering_unverified_email_cannot_replace_password(self):
        """Pre-verification takeover: a second signup for someone else's
        pending address must not swap in the second signer's password."""
        self.register(password='victimpass123')
        self.register(password='attackerpass123')

        pending = PendingRegistration.objects.get(email='new@example.com')
        self.client.get(f'/api/auth/verify-email/{pending.token}/')

        user = User.objects.get(email='new@example.com')
        self.assertTrue(user.check_password('victimpass123'))
        self.assertFalse(user.check_password('attackerpass123'))

    def test_re_registering_after_link_expired_starts_fresh(self):
        self.register(password='firstpass123')
        pending = PendingRegistration.objects.get(email='new@example.com')
        old_token = pending.token
        pending.created_at = timezone.now() - timedelta(days=30)
        pending.save(update_fields=['created_at'])

        self.register(password='secondpass123')

        pending.refresh_from_db()
        self.assertNotEqual(pending.token, old_token)
        self.client.get(f'/api/auth/verify-email/{pending.token}/')
        self.assertTrue(User.objects.get(email='new@example.com').check_password('secondpass123'))

    def test_register_rejects_weak_passwords(self):
        for weak in ('12345678', 'password', 'qwertyuiop'):
            res = self.register(password=weak)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST, weak)
            self.assertIn('password', res.data)
        self.assertFalse(PendingRegistration.objects.exists())

    def test_verify_email_when_user_already_exists_does_not_crash(self):
        self.register()
        pending = PendingRegistration.objects.get(email='new@example.com')
        User.objects.create_user(email='NEW@example.com', password='somepass123')

        res = self.client.get(f'/api/auth/verify-email/{pending.token}/')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(User.objects.filter(email__iexact='new@example.com').count(), 1)
        self.assertFalse(PendingRegistration.objects.exists())

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


class LoginThrottleTests(APITestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_spoofed_x_forwarded_for_cannot_bypass_login_limit(self):
        """nginx appends the real client IP last; earlier entries are client-controlled."""
        codes = []
        for i in range(7):
            res = self.client.post(
                '/api/auth/login/',
                {'email': 'nobody@example.com', 'password': 'wrongpass123'},
                format='json',
                HTTP_X_FORWARDED_FOR=f'10.0.0.{i}, 203.0.113.7',
            )
            codes.append(res.status_code)
        self.assertEqual(codes[:5], [status.HTTP_401_UNAUTHORIZED] * 5)
        self.assertEqual(codes[5:], [status.HTTP_429_TOO_MANY_REQUESTS] * 2)
