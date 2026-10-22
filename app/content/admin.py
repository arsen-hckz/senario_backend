from django.contrib import admin

from .models import PageImage, PageText


@admin.register(PageText)
class PageTextAdmin(admin.ModelAdmin):
    list_display = ('page', 'key', 'updated_at')
    list_filter = ('page',)


@admin.register(PageImage)
class PageImageAdmin(admin.ModelAdmin):
    list_display = ('page', 'key', 'updated_at')
    list_filter = ('page',)
