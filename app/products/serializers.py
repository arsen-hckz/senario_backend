from django.utils.text import slugify
from rest_framework import serializers
from .models import Category, Product, ProductVariant


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name', 'slug')


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = ('id', 'size', 'stock')


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True, required=False
    )
    variants = ProductVariantSerializer(many=True, read_only=True)
    effective_price = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            'id', 'name', 'slug', 'description',
            'price', 'sale_price', 'effective_price',
            'image', 'stock', 'is_active',
            'category', 'category_id', 'variants',
            'created_at',
        )
        read_only_fields = ('created_at',)
        extra_kwargs = {'slug': {'required': False}}

    def _unique_slug(self, name, pk=None):
        base = slugify(name)
        slug = base
        n = 1
        qs = Product.objects.filter(slug=slug)
        if pk:
            qs = qs.exclude(pk=pk)
        while qs.exists():
            slug = f'{base}-{n}'
            n += 1
            qs = Product.objects.filter(slug=slug)
            if pk:
                qs = qs.exclude(pk=pk)
        return slug

    def create(self, validated_data):
        validated_data.setdefault('slug', self._unique_slug(validated_data['name']))
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'name' in validated_data and 'slug' not in validated_data:
            validated_data['slug'] = self._unique_slug(validated_data['name'], pk=instance.pk)
        return super().update(instance, validated_data)
