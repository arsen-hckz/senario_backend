from django.db import models

from products.models import Product


class SalePost(models.Model):
    """A promo card on the Sale page spotlighting one product. Stores no image
    or price of its own: the storefront shows the product's current ones."""
    product  = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='sale_posts')
    headline = models.CharField(max_length=200)
    note     = models.CharField(max_length=300, blank=True)
    order    = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.headline
