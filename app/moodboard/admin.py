from django.contrib import admin
from .models import MoodboardPhoto


@admin.register(MoodboardPhoto)
class MoodboardPhotoAdmin(admin.ModelAdmin):
    list_display = ('title', 'order', 'image', 'external_src')
    ordering = ('order',)
    search_fields = ('title',)
