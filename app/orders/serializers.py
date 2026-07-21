from rest_framework import serializers
from .models import Order, OrderItem
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
            cart = Cart.objects.prefetch_related('items__product').get(user=user)
        except Cart.DoesNotExist:
            raise serializers.ValidationError('No cart found.')
        if not cart.items.exists():
            raise serializers.ValidationError('Your cart is empty.')
        self._cart = cart
        return attrs

    def create(self, validated_data):
        cart = self._cart
        total = cart.total
        order = Order.objects.create(total=total, **validated_data)
        for item in cart.items.select_related('product', 'variant').all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                variant=item.variant,
                product_name=item.product.name,
                size=item.variant.size if item.variant else '',
                price=item.product.effective_price,
                qty=item.qty,
            )
        cart.items.all().delete()
        return order


class OrderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ('status',)
