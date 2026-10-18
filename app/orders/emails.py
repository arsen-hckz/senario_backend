import logging

from django.conf import settings

from users.emails import frontend_url, send_branded_email
from .receipt import build_receipt_pdf, euro, vat_breakdown

logger = logging.getLogger(__name__)


def order_url(order):
    """Where the email's button goes. Guests have no account: their link
    carries the order's secret, after "#" so it never reaches a server log."""
    if order.is_guest:
        return frontend_url(f'order?id={order.pk}#t={order.access_token}')
    return frontend_url('account-orders')


def send_order_confirmation(order, transaction_id=''):
    """Email the customer that their order is paid, with the PDF receipt.

    Never raises: the payment is already recorded by the time this runs, so
    a mail outage must not turn into an error for Viva's webhook. Failures
    are logged at ERROR, which emails staff to send it by hand (Django admin
    > Orders > "Resend confirmation email").
    """
    to = order.email or (order.user.email if order.user else '')
    if not to:
        logger.error('Order #%s has no email address: confirmation not sent', order.pk)
        return False
    try:
        items = list(order.items.all())
        vat = vat_breakdown(order.total)[1]
        send_branded_email(
            to,
            f'Your {settings.BRAND_NAME} order #{order.pk} is confirmed',
            'order_confirmed',
            {
                'first_name': order.full_name.split(' ')[0] if order.full_name else '',
                'order': order,
                'items': [
                    {'name': i.product_name, 'size': i.size, 'qty': i.qty, 'subtotal': euro(i.subtotal)}
                    for i in items
                ],
                'shipping': euro(order.shipping) if order.shipping else 'Free',
                'total': euro(order.total),
                'vat': euro(vat),
                'vat_rate': settings.VAT_RATE_PERCENT,
                'action_url': order_url(order),
            },
            template_dir='orders/email',
            attachments=[(
                f'{settings.BRAND_NAME}-order-{order.pk}.pdf',
                build_receipt_pdf(order, transaction_id),
                'application/pdf',
            )],
        )
    except Exception:
        logger.exception('Could not send the confirmation email for Order #%s', order.pk)
        return False
    return True
