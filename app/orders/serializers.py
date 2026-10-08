from django.db import transaction
from rest_framework import serializers
from .models import Order, OrderItem
from .stock import unavailable_items
from cart.models import Cart


class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ('id', 'product_name', 'size', 'price', 'qty', 'subtotal')


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            'id', 'status', 'total',
            'full_name', 'address', 'city', 'country', 'postal_code',
            'items', 'created_at',
        )
        read_only_fields = ('id', 'status', 'total', 'items', 'created_at')


class CreateOrderSerializer(serializers.Serializer):
    full_name   = serializers.CharField(max_length=120)
    address     = serializers.CharField(max_length=255)
    city        = serializers.CharField(max_length=100)
    country     = serializers.CharField(max_length=100)
    postal_code = serializers.CharField(max_length=20)

    def validate(self, attrs):
        user = self.context['request'].user
        try:
            cart = Cart.objects.get(user=user)
        except Cart.DoesNotExist:
            raise serializers.ValidationError('No cart found.')
        items = list(cart.items.select_related('product', 'variant'))
        if not items:
            raise serializers.ValidationError('Your cart is empty.')
        unavailable = unavailable_items(
            (item.product.name, item.product, item.variant, item.qty) for item in items
        )
        if unavailable:
            raise serializers.ValidationError(
                'Some items are no longer available: ' + ', '.join(unavailable)
            )
        self._cart = cart
        self._items = items
        return attrs

    def create(self, validated_data):
        # All-or-nothing: an error halfway must not leave a partial order
        # behind, or empty the cart without an order to show for it.
        with transaction.atomic():
            total = sum(item.product.effective_price * item.qty for item in self._items)
            order = Order.objects.create(total=total, **validated_data)
            OrderItem.objects.bulk_create([
                OrderItem(
                    order=order,
                    product=item.product,
                    variant=item.variant,
                    product_name=item.product.name,
                    size=item.variant.size if item.variant else '',
                    price=item.product.effective_price,
                    qty=item.qty,
                )
                for item in self._items
            ])
            self._cart.items.all().delete()
        return order


class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ('status',)
