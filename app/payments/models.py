from django.conf import settings
from django.db import models

from orders.models import Order


class Checkout(models.Model):
    """What the customer is about to pay for: their details and a snapshot of
    the items at the prices they were quoted.

    No Order exists until Viva confirms the payment — the webhook then turns
    the checkout into a confirmed Order. Abandoned checkouts are deleted after
    24 hours (see `delete_old_checkouts`).
    """
    # Null for guest checkouts, and if the account was deleted meanwhile.
    user        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='checkouts')
    # Secret the browser shows to read the checkout's outcome. A guest's
    # order later takes the same secret, so the return page can open it.
    token       = models.CharField(max_length=64, editable=False)
    full_name   = models.CharField(max_length=120)
    email       = models.EmailField()
    phone       = models.CharField(max_length=30)
    address     = models.CharField(max_length=255)
    city        = models.CharField(max_length=100)
    country     = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    # [{product_id, variant_id, product_name, size, price, qty}], price as a string.
    items       = models.JSONField()
    shipping    = models.DecimalField(max_digits=8, decimal_places=2)
    total       = models.DecimalField(max_digits=10, decimal_places=2)
    # Set by the webhook once paid.
    order       = models.OneToOneField(Order, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='checkout')
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f'Checkout #{self.pk} — ' + (f'Order #{self.order_id}' if self.order_id else 'not paid')


class Payment(models.Model):
    """One Viva Smart Checkout attempt for a Checkout.

    `order` is set once the payment confirms (it's also set on payments made
    before checkouts existed, which were taken against a pending Order).
    """
    class Status(models.TextChoices):
        PENDING   = 'pending',   'Pending'
        PAID      = 'paid',      'Paid'
        FAILED    = 'failed',    'Failed'
        # Charged, but no order could be confirmed for it (already paid,
        # cancelled, or its checkout was gone) — refund it in Viva's portal.
        REFUND_NEEDED = 'refund_needed', 'Paid — refund needed'
        # Refunded in full through Viva (the refund webhook sets it).
        REFUNDED  = 'refunded',  'Refunded'

    checkout            = models.ForeignKey(Checkout, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name='payments')
    order               = models.ForeignKey(Order, on_delete=models.CASCADE, null=True, blank=True,
                                            related_name='payments')
    viva_order_code     = models.CharField(max_length=32, unique=True)
    viva_transaction_id = models.CharField(max_length=64, blank=True)
    amount              = models.DecimalField(max_digits=10, decimal_places=2)
    status              = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        target = f'Order #{self.order_id}' if self.order_id else f'Checkout #{self.checkout_id}'
        return f'Payment #{self.pk} for {target} — {self.status}'
