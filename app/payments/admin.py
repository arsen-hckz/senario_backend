from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'status', 'amount', 'viva_order_code', 'viva_transaction_id', 'created_at')
    list_filter = ('status',)
    search_fields = ('viva_order_code', 'viva_transaction_id', 'order__id')
    readonly_fields = ('order', 'viva_order_code', 'viva_transaction_id', 'amount', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False
