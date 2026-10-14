from rest_framework import serializers

from products.models import Product
from .models import SalePost


class SalePostSerializer(serializers.ModelSerializer):
    product_slug = serializers.SlugRelatedField(
        source='product', slug_field='slug', queryset=Product.objects.all(),
    )

    class Meta:
        model = SalePost
        fields = ('id', 'product_slug', 'headline', 'note', 'order')
        read_only_fields = ('order',)
