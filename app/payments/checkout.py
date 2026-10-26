"""Checkouts: an Order is only created once Viva confirms the payment."""
import secrets
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from cart.models import CartItem
from orders.models import Order, OrderItem
from orders.shipping import shipping_for
from orders.stock import decrement_order_stock
from products.models import Product, ProductVariant

from .models import Checkout

# Unpaid checkouts are deleted after this (the privacy policy says so).
# Well beyond the life of a Viva payment page; a payment that still arrives
# later is flagged for a refund rather than lost.
KEEP_UNPAID_FOR = timedelta(hours=24)


def delete_old_checkouts():
    """Delete unpaid checkouts older than KEEP_UNPAID_FOR; returns how many.
    Runs on every new checkout and hourly from cron (delete_old_checkouts)."""
    old = Checkout.objects.filter(order__isnull=True, created_at__lt=timezone.now() - KEEP_UNPAID_FOR)
    return old.delete()[1].get('payments.Checkout', 0)


def open_checkout(lines, details, user=None):
    """A Checkout for `lines` (already checked against stock) at today's prices."""
    delete_old_checkouts()
    subtotal = sum(line.subtotal for line in lines)
    shipping = shipping_for(subtotal)
    return Checkout.objects.create(
        user=user,
        token=secrets.token_urlsafe(32),
        items=[
            {
                'product_id': line.product.pk,
                'variant_id': line.variant.pk if line.variant else None,
                'product_name': line.product.name,
                'size': line.variant.size if line.variant else '',
                'price': str(line.product.effective_price),
                'qty': line.qty,
            }
            for line in lines
        ],
        shipping=shipping,
        total=subtotal + shipping,
        **details,
    )


def create_paid_order(checkout, logger):
    """The confirmed Order for a checkout whose payment Viva just verified,
    with its stock taken. Must run inside a transaction with the checkout locked."""
    order = Order.objects.create(
        user=checkout.user,
        # A guest's order opens with the secret their browser already holds.
        access_token='' if checkout.user_id else checkout.token,
        status=Order.Status.CONFIRMED,
        total=checkout.total,
        shipping=checkout.shipping,
        full_name=checkout.full_name,
        email=checkout.email,
        phone=checkout.phone,
        address=checkout.address,
        city=checkout.city,
        country=checkout.country,
        postal_code=checkout.postal_code,
    )
    # The product or size may have been deleted since: the snapshot still
    # says what was bought, the links just stay empty.
    product_ids = set(Product.objects.filter(pk__in=[i['product_id'] for i in checkout.items]).values_list('pk', flat=True))
    variant_ids = set(ProductVariant.objects.filter(
        pk__in=[i['variant_id'] for i in checkout.items if i['variant_id']],
    ).values_list('pk', flat=True))
    OrderItem.objects.bulk_create([
        OrderItem(
            order=order,
            product_id=item['product_id'] if item['product_id'] in product_ids else None,
            variant_id=item['variant_id'] if item['variant_id'] in variant_ids else None,
            product_name=item['product_name'],
            size=item['size'],
            price=Decimal(item['price']),
            qty=item['qty'],
        )
        for item in checkout.items
    ])
    decrement_order_stock(order, logger)

    checkout.order = order
    checkout.save(update_fields=['order'])

    if checkout.user_id:
        # What was paid for leaves the cart; anything added since stays.
        for item in checkout.items:
            CartItem.objects.filter(
                cart__user_id=checkout.user_id, product_id=item['product_id'], variant_id=item['variant_id'],
            ).delete()
    return order
