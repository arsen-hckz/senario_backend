from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Category, Product, ProductImage, ProductVariant


@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
@receiver(post_save, sender=Product)
@receiver(post_delete, sender=Product)
@receiver(post_save, sender=ProductImage)
@receiver(post_delete, sender=ProductImage)
@receiver(post_save, sender=ProductVariant)
@receiver(post_delete, sender=ProductVariant)
def clear_product_list_cache(**kwargs):
    # The public product list is cached for 5 minutes. Clear it on any change,
    # whether it came through the API, the Django admin or a stock decrement.
    transaction.on_commit(lambda: cache.delete_pattern('products:*'))


@receiver(post_delete, sender=ProductImage)
def delete_product_image_file(sender, instance, **kwargs):
    # Deleting the row (directly, or with its product) leaves the file on disk otherwise.
    if instance.image:
        name = instance.image.name
        storage = instance.image.storage
        transaction.on_commit(lambda: storage.delete(name))
