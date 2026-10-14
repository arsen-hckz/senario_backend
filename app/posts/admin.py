from django.contrib import admin

from .models import SalePost


@admin.register(SalePost)
class SalePostAdmin(admin.ModelAdmin):
    list_display = ('headline', 'product', 'order')
    list_editable = ('order',)
