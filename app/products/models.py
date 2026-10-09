import os

from django.db import models

from moodboard.image_utils import optimize_image_file


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    category   = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name='products')
    name       = models.CharField(max_length=200)
    slug       = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price      = models.DecimalField(max_digits=8, decimal_places=2)
    sale_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    stock      = models.PositiveIntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def effective_price(self):
        return self.sale_price if self.sale_price else self.price


class ProductImage(models.Model):
    """One photo of a product. The lowest `order` is the cover shown in
    listings, the cart and checkout."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image   = models.ImageField(upload_to='products/')
    order   = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.product.name} — photo {self.order + 1}'

    def save(self, *args, **kwargs):
        # Phone photos are often 5-15 MB. Shrink every new upload (API or
        # Django admin) before it is stored and served to shoppers.
        if self.image and not self.image._committed:
            self.image = optimize_image_file(self.image.file, name=os.path.basename(self.image.name))
        super().save(*args, **kwargs)


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    size    = models.CharField(max_length=10)
    stock   = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('product', 'size')

    def __str__(self):
        return f'{self.product.name} — {self.size}'
