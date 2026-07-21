from django.db import models
from django.conf import settings
from products.models import Product, ProductVariant


class Cart(models.Model):
    user       = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Cart ({self.user.email})'

    @property
    def total(self):
        return sum(item.subtotal for item in self.items.all())


class CartItem(models.Model):
    cart    = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True)
    qty     = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('cart', 'product', 'variant')

    def __str__(self):
        return f'{self.qty}x {self.product.name}'

    @property
    def subtotal(self):
        return self.product.effective_price * self.qty
