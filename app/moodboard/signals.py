from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import MoodboardPhoto


def _delete_file_after_commit(field_file):
    name, storage = field_file.name, field_file.storage
    transaction.on_commit(lambda: storage.delete(name))


@receiver(post_delete, sender=MoodboardPhoto)
def delete_photo_file(sender, instance, **kwargs):
    if instance.image:
        _delete_file_after_commit(instance.image)


@receiver(pre_save, sender=MoodboardPhoto)
def delete_replaced_photo_file(sender, instance, **kwargs):
    # Uploading a new image for an existing photo would otherwise orphan the old file.
    if not instance.pk:
        return
    old = MoodboardPhoto.objects.filter(pk=instance.pk).values_list('image', flat=True).first()
    if old and old != instance.image.name:
        _delete_file_after_commit(MoodboardPhoto(image=old).image)
