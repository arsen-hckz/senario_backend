import logging

from django.utils import timezone

from .models import Order
from .stock import decrement_order_stock, increment_order_stock

logger = logging.getLogger(__name__)

# An order in one of these holds its stock: the Viva webhook takes it off when
# the payment confirms the order, so staff moving an order in or out of this
# set by hand has to take or give back stock the same way.
STOCK_TAKEN = {Order.Status.CONFIRMED, Order.Status.SHIPPED, Order.Status.DELIVERED}


def apply_status_change(order, old_status):
    """Stock and payment side effects of staff changing an order's status.
    Call inside a transaction, after the new status is saved. Returns True
    when a Viva payment was flagged for a refund."""
    from payments.models import Payment

    was_taken = old_status in STOCK_TAKEN
    now_taken = order.status in STOCK_TAKEN
    if was_taken == now_taken:
        return False

    if now_taken:
        # Confirmed by hand (e.g. paid another way) or un-cancelled.
        decrement_order_stock(order, logger)
        return False

    increment_order_stock(order)
    # Released after a Viva payment: the money has to go back too. Flagging
    # it also lets the customer pay again if the order goes back to pending.
    flagged = order.payments.filter(status=Payment.Status.PAID).update(
        status=Payment.Status.REFUND_NEEDED, updated_at=timezone.now(),
    )
    if flagged:
        logger.warning('Order #%s moved to %s after payment: refund it in Viva', order.pk, order.status)
    return bool(flagged)
