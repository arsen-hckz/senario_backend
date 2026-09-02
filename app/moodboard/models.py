from django.db import models


class MoodboardPhoto(models.Model):
    image        = models.ImageField(upload_to='moodboard/', blank=True, null=True)
    external_src = models.CharField(max_length=500, blank=True)
    title        = models.CharField(max_length=200, blank=True)
    body         = models.TextField(blank=True)
    order        = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.title or f'Photo {self.pk}'
