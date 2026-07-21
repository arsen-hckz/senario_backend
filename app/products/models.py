from django.db import models


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
    image      = models.ImageField(upload_to='products/', blank=True)
    stock      = models.PositiveIntegerField(default=0)
    is_active  = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def effective_price(self):
        return self.sale_price if self.sale_price else self.price


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    size    = models.CharField(max_length=10)
    stock   = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('product', 'size')

    def __str__(self):
        return f'{self.product.name} — {self.size}'
