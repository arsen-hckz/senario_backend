from django.contrib import admin

from .models import Checkout, Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'checkout', 'status', 'amount', 'viva_order_code', 'viva_transaction_id', 'created_at')
    list_filter = ('status',)
    search_fields = ('viva_order_code', 'viva_transaction_id', 'order__id')
    readonly_fields = ('order', 'checkout', 'viva_order_code', 'viva_transaction_id', 'amount', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(Checkout)
class CheckoutAdmin(admin.ModelAdmin):
    """Checkouts that were started; the ones without an order were never paid.
    Read-only: an order only ever comes from a verified payment."""
    list_display = ('id', 'order', 'user', 'full_name', 'email', 'total', 'created_at')
    search_fields = ('full_name', 'email', 'phone')
    readonly_fields = [f.name for f in Checkout._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
