from django.contrib import admin

from .models import PageText


@admin.register(PageText)
class PageTextAdmin(admin.ModelAdmin):
    list_display = ('page', 'key', 'updated_at')
    list_filter = ('page',)
