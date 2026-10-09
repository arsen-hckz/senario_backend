from datetime import date
from email.mime.image import MIMEImage

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.contrib.staticfiles.finders import find
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

LOGO_STATIC_PATH = 'users/email/logo.jpg'
LOGO_CID = 'brand-logo'


def build_verification_url(pending, request=None):
    if settings.FRONTEND_URL:
        return f'{settings.FRONTEND_URL.rstrip("/")}/verify-email.html?token={pending.token}'

    path = reverse('auth-verify-email', kwargs={'token': pending.token})
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def _frontend_url(page, request=None):
    if settings.FRONTEND_URL:
        return f'{settings.FRONTEND_URL.rstrip("/")}/{page}'
    if request is not None:
        return request.build_absolute_uri(f'/{page}')
    return f'/{page}'


def build_password_reset_url(user, request=None):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f'{_frontend_url("reset-password.html", request)}?uid={uid}&token={token}'


def _send_branded_email(to, subject, template, context):
    context = {
        'brand_name': settings.BRAND_NAME,
        'current_year': date.today().year,
        'logo_cid': LOGO_CID,
        **context,
    }
    text_body = render_to_string(f'users/email/{template}.txt', context)
    html_body = render_to_string(f'users/email/{template}.html', context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
        reply_to=[settings.SUPPORT_EMAIL],
    )
    message.attach_alternative(html_body, 'text/html')
    message.mixed_subtype = 'related'

    logo_path = find(LOGO_STATIC_PATH)
    if logo_path:
        with open(logo_path, 'rb') as logo_file:
            mime_image = MIMEImage(logo_file.read())
        mime_image.add_header('Content-ID', f'<{LOGO_CID}>')
        mime_image.add_header('Content-Disposition', 'inline', filename='logo.jpg')
        message.attach(mime_image)

    message.send(fail_silently=False)


def send_verification_email(pending, request=None):
    _send_branded_email(pending.email, f'Verify your email for {settings.BRAND_NAME}', 'verify_email', {
        'first_name': pending.first_name,
        'action_url': build_verification_url(pending, request),
        'expiry_days': settings.EMAIL_VERIFICATION_TIMEOUT_DAYS,
    })


def send_password_reset_email(user, request=None):
    _send_branded_email(user.email, f'Reset your {settings.BRAND_NAME} password', 'password_reset', {
        'first_name': user.first_name,
        'action_url': build_password_reset_url(user, request),
        'expiry_minutes': settings.PASSWORD_RESET_TIMEOUT // 60,
    })


def send_account_exists_email(user, request=None):
    """Sent instead of an error when someone registers an address that already
    has an account, so the register endpoint can't be used to probe which
    emails are customers."""
    _send_branded_email(user.email, f'You already have a {settings.BRAND_NAME} account', 'account_exists', {
        'first_name': user.first_name,
        'action_url': _frontend_url('login.html', request),
        'reset_url': _frontend_url('forgot-password.html', request),
    })
