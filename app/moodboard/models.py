import logging
import os

from django.db import models

from .image_utils import make_thumbnail

logger = logging.getLogger(__name__)


class MoodboardPhoto(models.Model):
    image        = models.ImageField(upload_to='moodboard/', blank=True, null=True)
    # Small version for the grid; generated from `image` on save.
    thumb        = models.ImageField(upload_to='moodboard/thumbs/', blank=True, null=True)
    external_src = models.CharField(max_length=500, blank=True)
    title        = models.CharField(max_length=200, blank=True)
    body         = models.TextField(blank=True)
    order        = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title or f'Photo {self.pk}'

    def save(self, *args, **kwargs):
        new_upload = bool(self.image) and not self.image._committed
        if not self.image:
            self.thumb = None  # moodboard.signals deletes the old file
        super().save(*args, **kwargs)
        if new_upload or (self.image and not self.thumb):
            self.refresh_thumbnail()

    def refresh_thumbnail(self):
        try:
            with self.image.open('rb') as f:
                thumb = make_thumbnail(f, name=os.path.basename(self.image.name))
        except (OSError, ValueError):
            # Missing/unreadable file: keep the photo saveable; the page shows
            # the full image for this tile instead.
            logger.warning('No thumbnail for moodboard photo %s (%s)', self.pk, self.image.name, exc_info=True)
            return
        self.thumb.save(thumb.name, thumb, save=False)
        super().save(update_fields=['thumb'])
