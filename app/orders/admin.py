from django.contrib import admin
from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_name', 'size', 'price', 'qty', 'subtotal')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'full_name', 'status', 'total', 'created_at')
    list_filter = ('status',)
    search_fields = ('full_name', 'user__email')
    readonly_fields = ('user', 'total', 'created_at')
    list_editable = ('status',)
    inlines = (OrderItemInline,)
