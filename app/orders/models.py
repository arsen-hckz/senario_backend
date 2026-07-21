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

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='orders')
    status     = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    total      = models.DecimalField(max_digits=10, decimal_places=2)
    # shipping address snapshot
    full_name  = models.CharField(max_length=120)
    address    = models.CharField(max_length=255)
    city       = models.CharField(max_length=100)
    country    = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Order #{self.pk} — {self.status}'


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
