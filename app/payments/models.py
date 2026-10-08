from django.db import models

from orders.models import Order


class Payment(models.Model):
    """One Viva Smart Checkout attempt against an Order.

    Kept separate from Order (rather than fields on it) so a failed/abandoned
    attempt doesn't need to mutate the order — a customer can retry checkout
    and get a fresh row without losing the earlier attempt's audit trail.
    """
    class Status(models.TextChoices):
        PENDING   = 'pending',   'Pending'
        PAID      = 'paid',      'Paid'
        FAILED    = 'failed',    'Failed'
        # Charged, but the order was already paid or cancelled — refund it in Viva's portal.
        REFUND_NEEDED = 'refund_needed', 'Paid — refund needed'

    order               = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    viva_order_code     = models.CharField(max_length=32, unique=True)
    viva_transaction_id = models.CharField(max_length=64, blank=True)
    amount              = models.DecimalField(max_digits=10, decimal_places=2)
    status              = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Payment #{self.pk} for Order #{self.order_id} — {self.status}'
