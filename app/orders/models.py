from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from products.models import Product, ProductVariant


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING    = 'pending',    'Pending'
        CONFIRMED  = 'confirmed',  'Confirmed'
        SHIPPED    = 'shipped',    'Shipped'
        DELIVERED  = 'delivered',  'Delivered'
        CANCELLED  = 'cancelled',  'Cancelled'

    # Null for guest orders, which are opened with `access_token` instead.
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    access_token = models.CharField(max_length=64, blank=True, editable=False)
    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # What the customer pays: the items plus `shipping`.
    total      = models.DecimalField(max_digits=10, decimal_places=2)
    shipping   = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    # contact + shipping address snapshot (email/phone are blank on orders
    # placed before checkout started sending them)
    full_name  = models.CharField(max_length=120)
    email      = models.EmailField(blank=True)
    phone      = models.CharField(max_length=30, blank=True)
    address    = models.CharField(max_length=255)
    city       = models.CharField(max_length=100)
    country    = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Order #{self.pk} — {self.status}'

    def clean(self):
        # Run by Django admin forms. Orders only exist once paid, so staff
        # can't make one "pending"; old pending orders may stay as they are.
        if self.status == self.Status.PENDING:
            old = Order.objects.filter(pk=self.pk).values_list('status', flat=True).first() if self.pk else None
            if old != self.Status.PENDING:
                raise ValidationError({'status': 'An order can no longer be set to pending.'})

    @property
    def is_guest(self):
        return bool(self.access_token)

    @property
    def subtotal(self):
        return self.total - self.shipping


class OrderItem(models.Model):
    order      = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product    = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    variant    = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    product_name = models.CharField(max_length=200)
    size       = models.CharField(max_length=10, blank=True)
    price      = models.DecimalField(max_digits=8, decimal_places=2)
    qty        = models.PositiveIntegerField()

    def __str__(self):
        return f'{self.qty}x {self.product_name}'

    @property
    def subtotal(self):
        return self.price * self.qty
