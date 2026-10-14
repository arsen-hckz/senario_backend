import os

from django.db import migrations
from django.db.models import Q


def backfill_thumbnails(apps, schema_editor):
    """Grid-size versions of the photos uploaded before thumbnails existed."""
    from moodboard.image_utils import make_thumbnail

    MoodboardPhoto = apps.get_model('moodboard', 'MoodboardPhoto')
    # The new column is NULL on existing rows, '' after a cleared upload.
    missing = Q(thumb='') | Q(thumb__isnull=True)
    for photo in MoodboardPhoto.objects.exclude(image='').exclude(image__isnull=True).filter(missing):
        try:
            with photo.image.open('rb') as f:
                thumb = make_thumbnail(f, name=os.path.basename(photo.image.name))
        except (OSError, ValueError) as exc:
            # A missing or unreadable file must not block the deploy; the
            # page falls back to the full image for this one.
            print(f'  skipped moodboard photo {photo.pk}: {exc}')
            continue
        photo.thumb.save(thumb.name, thumb, save=False)
        photo.save(update_fields=['thumb'])


class Migration(migrations.Migration):

    dependencies = [
        ('moodboard', '0002_moodboardphoto_thumb'),
    ]

    operations = [
        migrations.RunPython(backfill_thumbnails, migrations.RunPython.noop),
    ]
