from django.db import models


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
