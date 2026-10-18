from rest_framework import serializers
from orders.shipping import shipping_for
from products.serializers import ProductSerializer, ProductVariantSerializer
from .models import Cart, CartItem


class CartItemSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    variant = ProductVariantSerializer(read_only=True)
    subtotal = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    needs_size = serializers.BooleanField(read_only=True)

    class Meta:
        model = CartItem
        fields = ('id', 'product', 'variant', 'qty', 'subtotal', 'needs_size')


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    item_count = serializers.SerializerMethodField()
    # `total` is the items only; what checkout charges is `grand_total`.
    shipping = serializers.SerializerMethodField()
    grand_total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ('id', 'items', 'total', 'shipping', 'grand_total', 'item_count', 'updated_at')

    def get_item_count(self, obj):
        return sum(i.qty for i in obj.items.all())

    def get_shipping(self, obj):
        return f'{shipping_for(obj.total):.2f}'

    def get_grand_total(self, obj):
        return f'{obj.total + shipping_for(obj.total):.2f}'


def quote_data(lines, dropped, context):
    """A guest cart priced like CartSerializer's output, so the storefront
    renders both the same way. Item ids are "<product>-<size id or 0>"."""
    subtotal = sum((line.subtotal for line in lines), start=0)
    shipping = shipping_for(subtotal)
    return {
        'items': [
            {
                'id': line.key,
                'product': ProductSerializer(line.product, context=context).data,
                'variant': ProductVariantSerializer(line.variant).data if line.variant else None,
                'qty': line.qty,
                'subtotal': f'{line.subtotal:.2f}',
                'needs_size': line.problem == 'Please choose a size.',
                'problem': line.problem,
            }
            for line in lines
        ],
        'total': f'{subtotal:.2f}',
        'shipping': f'{shipping:.2f}',
        'grand_total': f'{subtotal + shipping:.2f}',
        'item_count': sum(line.qty for line in lines),
        'dropped': dropped,
    }
