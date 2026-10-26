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


def customer_email(order):
    return order.email or (order.user.email if order.user else '')


def _order_context(order):
    """What every order email shows: the lines, delivery and total."""
    return {
        'first_name': order.full_name.split(' ')[0] if order.full_name else '',
        'order': order,
        'items': [
            {'name': i.product_name, 'size': i.size, 'qty': i.qty, 'subtotal': euro(i.subtotal)}
            for i in order.items.all()
        ],
        'shipping': euro(order.shipping) if order.shipping else 'Free',
        'total': euro(order.total),
    }


def send_order_confirmation(order, transaction_id=''):
    """Email the customer that their order is paid, with the PDF receipt.

    Never raises: the payment is already recorded by the time this runs, so
    a mail outage must not turn into an error for Viva's webhook. Failures
    are logged at ERROR, which emails staff to send it by hand (Django admin
    > Orders > "Resend confirmation email").
    """
    to = customer_email(order)
    if not to:
        logger.error('Order #%s has no email address: confirmation not sent', order.pk)
        return False
    try:
        send_branded_email(
            to,
            f'Your {settings.BRAND_NAME} order #{order.pk} is confirmed',
            'order_confirmed',
            {
                **_order_context(order),
                'vat': euro(vat_breakdown(order.total)[1]),
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


def send_order_shipped(order):
    """Tell the customer their order is on its way (staff set it to shipped).
    Never raises: the status change is already saved."""
    to = customer_email(order)
    if not to:
        logger.error('Order #%s has no email address: shipping email not sent', order.pk)
        return False
    try:
        send_branded_email(
            to,
            f'Your {settings.BRAND_NAME} order #{order.pk} is on its way',
            'order_shipped',
            {**_order_context(order), 'action_url': order_url(order)},
            template_dir='orders/email',
        )
    except Exception:
        logger.exception('Could not send the shipping email for Order #%s', order.pk)
        return False
    return True


def send_new_order_alert(order):
    """Tell the shop a paid order came in. Never raises: the payment is
    already recorded; a failure is logged at ERROR (which emails staff too)."""
    try:
        send_branded_email(
            settings.ORDER_ALERT_EMAIL,
            f'New order #{order.pk} — {euro(order.total)}',
            'new_order',
            {
                **_order_context(order),
                'first_name': '',
                'customer_email': customer_email(order),
                'action_url': frontend_url('admin'),
            },
            template_dir='orders/email',
        )
    except Exception:
        logger.exception('Could not send the new-order alert for Order #%s', order.pk)
        return False
    return True
