from decimal import Decimal

from django.conf import settings


def shipping_for(subtotal):
    """Delivery charge for an order whose items come to `subtotal`."""
    if subtotal <= 0:
        return Decimal('0.00')
    free_over = settings.FREE_SHIPPING_OVER
    if free_over and subtotal >= Decimal(free_over):
        return Decimal('0.00')
    return Decimal(settings.SHIPPING_FEE)


def shipping_rule():
    """What the storefront shows before checkout ("free over €50")."""
    return {
        'fee': settings.SHIPPING_FEE,
        'free_over': settings.FREE_SHIPPING_OVER or None,
    }
