from django.contrib import admin, messages
from django.db import transaction

from .emails import send_order_confirmation
from .models import Order, OrderItem
from .status import apply_status_change


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('product_name', 'size', 'price', 'qty', 'subtotal')
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'full_name', 'phone', 'status', 'total', 'created_at')
    list_filter = ('status',)
    search_fields = ('full_name', 'email', 'phone', 'user__email')
    readonly_fields = ('user', 'shipping', 'total', 'created_at')
    list_editable = ('status',)
    inlines = (OrderItemInline,)
    actions = ('resend_confirmation',)

    @admin.action(description='Resend confirmation email (with PDF receipt)')
    def resend_confirmation(self, request, queryset):
        from payments.models import Payment
        sent = 0
        for order in queryset:
            paid = order.payments.filter(status=Payment.Status.PAID).first()
            sent += send_order_confirmation(order, paid.viva_transaction_id if paid else '')
        self.message_user(request, f'Sent {sent} of {queryset.count()} confirmation email(s).')

    def save_model(self, request, obj, form, change):
        # Same stock/refund handling as the storefront admin's status dropdown.
        with transaction.atomic():
            old_status = Order.objects.select_for_update().filter(pk=obj.pk).values_list('status', flat=True).first()
            super().save_model(request, obj, form, change)
            if change and old_status and apply_status_change(obj, old_status):
                self.message_user(
                    request, f'Order #{obj.pk} was paid through Viva: refund it in the Viva portal.',
                    level=messages.WARNING,
                )
