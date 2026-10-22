from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import PageImage


@receiver(post_delete, sender=PageImage)
def delete_page_image_file(sender, instance, **kwargs):
    # Replacing or resetting a photo deletes its row; remove the file too.
    if instance.image:
        name, storage = instance.image.name, instance.image.storage
        transaction.on_commit(lambda: storage.delete(name))


@receiver(pre_save, sender=PageImage)
def delete_replaced_page_image_file(sender, instance, **kwargs):
    # A new file on an existing row (Django admin) would orphan the old one.
    if not instance.pk:
        return
    old_name = PageImage.objects.filter(pk=instance.pk).values_list('image', flat=True).first()
    if old_name and old_name != instance.image.name:
        storage = instance.image.storage
        transaction.on_commit(lambda: storage.delete(old_name))
