import os

from django.db import models

from moodboard.image_utils import optimize_image_file


class PageText(models.Model):
    """A staff-edited text on a storefront page. Only changed texts have a
    row; the rest fall back to the defaults in content/pages.py."""
    page       = models.CharField(max_length=50)
    key        = models.CharField(max_length=50)
    value      = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('page', 'key')
        ordering = ['page', 'key']

    def __str__(self):
        return f'{self.page} / {self.key}'


class PageImage(models.Model):
    """A staff-uploaded photo replacing one built into a storefront page
    (slots in content/pages.py). No row = the page's own photo."""
    page       = models.CharField(max_length=50)
    key        = models.CharField(max_length=50)
    image      = models.ImageField(upload_to='content/')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('page', 'key')
        ordering = ['page', 'key']

    def __str__(self):
        return f'{self.page} / {self.key}'

    def save(self, *args, **kwargs):
        # Shrink phone-camera uploads before they are stored and served.
        if self.image and not self.image._committed:
            self.image = optimize_image_file(self.image.file, name=os.path.basename(self.image.name))
        super().save(*args, **kwargs)
