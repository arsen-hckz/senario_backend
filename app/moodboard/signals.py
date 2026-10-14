from django.db import transaction
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from .models import MoodboardPhoto


def _delete_file_after_commit(field_file):
    name, storage = field_file.name, field_file.storage
    transaction.on_commit(lambda: storage.delete(name))


@receiver(post_delete, sender=MoodboardPhoto)
def delete_photo_files(sender, instance, **kwargs):
    for field_file in (instance.image, instance.thumb):
        if field_file:
            _delete_file_after_commit(field_file)


@receiver(pre_save, sender=MoodboardPhoto)
def delete_replaced_photo_files(sender, instance, **kwargs):
    # A new image or thumbnail for an existing photo would otherwise orphan the old file.
    if not instance.pk:
        return
    old = MoodboardPhoto.objects.filter(pk=instance.pk).values('image', 'thumb').first() or {}
    for field in ('image', 'thumb'):
        old_name = old.get(field)
        if old_name and old_name != getattr(instance, field).name:
            _delete_file_after_commit(getattr(MoodboardPhoto(**{field: old_name}), field))
