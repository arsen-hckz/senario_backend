from datetime import date
from email.mime.image import MIMEImage

from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .tokens import email_verification_token

LOGO_STATIC_PATH = 'users/email/logo.jpg'
LOGO_CID = 'brand-logo'


def build_verification_url(user, request=None):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = email_verification_token.make_token(user)

    if settings.FRONTEND_URL:
        return f'{settings.FRONTEND_URL.rstrip("/")}/verify-email.html?uid={uid}&token={token}'

    path = reverse('auth-verify-email', kwargs={'uidb64': uid, 'token': token})
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def send_verification_email(user, request=None):
    context = {
        'brand_name': settings.BRAND_NAME,
        'first_name': user.first_name,
        'verification_url': build_verification_url(user, request),
        'expiry_days': settings.EMAIL_VERIFICATION_TIMEOUT_DAYS,
        'current_year': date.today().year,
        'logo_cid': LOGO_CID,
    }

    subject = f'Verify your email for {settings.BRAND_NAME}'
    text_body = render_to_string('users/email/verify_email.txt', context)
    html_body = render_to_string('users/email/verify_email.html', context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
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
