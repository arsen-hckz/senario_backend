from django.db import transaction
from django.db.models import Max
from django.utils.text import slugify
from rest_framework import serializers

from .models import Category, Product, ProductImage, ProductVariant

MAX_IMAGES_PER_PRODUCT = 12

# Display order for sizes; anything else (e.g. "One Size") goes after these.
SIZE_ORDER = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL']


def _size_rank(size):
    upper = size.upper()
    return (SIZE_ORDER.index(upper), '') if upper in SIZE_ORDER else (len(SIZE_ORDER), upper)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name', 'slug')


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = ('id', 'size', 'stock')


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ('id', 'image')


class ProductSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source='category', write_only=True, required=False
    )
    variants = ProductVariantSerializer(many=True, read_only=True)
    effective_price = serializers.DecimalField(max_digits=8, decimal_places=2, read_only=True)

    # Cover photo URL, kept as a single field so listings, cart and checkout
    # need no changes; `images` is the full ordered gallery.
    image  = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)

    # Gallery edits ride along with a normal create/PATCH (multipart):
    #   uploaded_images   new files, appended after the existing photos
    #   remove_image_ids  ids of this product's photos to delete
    #   image_order       the full new order: existing photo ids, and
    #                     "new-<n>" for the n-th file in uploaded_images
    uploaded_images  = serializers.ListField(
        child=serializers.ImageField(), write_only=True, required=False, max_length=MAX_IMAGES_PER_PRODUCT,
    )
    remove_image_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    image_order      = serializers.ListField(child=serializers.CharField(), write_only=True, required=False)

    # The full set of sizes and their stock, as a JSON string (the admin form
    # is multipart because of the photos): [{"size": "M", "stock": 4}, ...].
    # Sizes left out are removed; [] makes it a one-size product again.
    sizes = serializers.JSONField(write_only=True, required=False, binary=True)

    class Meta:
        model = Product
        fields = (
            'id', 'name', 'slug', 'description',
            'price', 'sale_price', 'effective_price',
            'image', 'images', 'uploaded_images', 'remove_image_ids', 'image_order', 'sizes',
            'stock', 'is_active',
            'category', 'category_id', 'variants',
            'created_at',
        )
        read_only_fields = ('created_at',)
        extra_kwargs = {'slug': {'required': False}}

    def get_image(self, obj):
        first = next(iter(obj.images.all()), None)  # uses the prefetch when present
        if first is None:
            return None
        request = self.context.get('request')
        url = first.image.url
        return request.build_absolute_uri(url) if request else url

    def validate_sizes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('Expected a list of {"size", "stock"} objects.')
        cleaned, seen = [], set()
        for entry in value:
            if not isinstance(entry, dict):
                raise serializers.ValidationError('Each size must be an object with "size" and "stock".')
            size = str(entry.get('size') or '').strip()
            if not size or len(size) > 10:
                raise serializers.ValidationError('Each size needs a name of up to 10 characters.')
            if size.upper() in seen:
                raise serializers.ValidationError(f'Size {size} is listed twice.')
            stock = entry.get('stock')
            if isinstance(stock, bool) or not isinstance(stock, int) or stock < 0:
                raise serializers.ValidationError(f'Stock for size {size} must be a whole number, 0 or more.')
            seen.add(size.upper())
            cleaned.append({'size': size, 'stock': stock})
        return cleaned

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['variants'] = sorted(data['variants'], key=lambda v: _size_rank(v['size']))
        return data

    def _apply_sizes(self, product, sizes):
        if sizes is None:
            return
        existing = {v.size.upper(): v for v in product.variants.all()}
        for entry in sizes:
            variant = existing.pop(entry['size'].upper(), None)
            if variant is None:
                ProductVariant.objects.create(product=product, size=entry['size'], stock=entry['stock'])
            elif variant.stock != entry['stock'] or variant.size != entry['size']:
                variant.stock, variant.size = entry['stock'], entry['size']
                variant.save(update_fields=['stock', 'size'])
        # Sizes no longer sold. Past orders keep their size text; carts holding
        # one are flagged as needing a size.
        for variant in existing.values():
            variant.delete()

    def validate(self, attrs):
        # A sale price of 0 would read as "no sale" (effective_price), and one
        # at or above the price would charge more than the struck-out price.
        price = attrs.get('price', getattr(self.instance, 'price', None))
        sale_price = attrs.get('sale_price', getattr(self.instance, 'sale_price', None))
        if sale_price is not None and price is not None and not 0 < sale_price < price:
            raise serializers.ValidationError(
                {'sale_price': 'The sale price must be more than 0 and less than the price.'}
            )

        new = len(attrs.get('uploaded_images', []))
        if new:
            existing = 0
            if self.instance is not None:
                removed = set(attrs.get('remove_image_ids', []))
                existing = self.instance.images.exclude(id__in=removed).count()
            if existing + new > MAX_IMAGES_PER_PRODUCT:
                raise serializers.ValidationError(
                    {'uploaded_images': f'A product can have at most {MAX_IMAGES_PER_PRODUCT} photos.'}
                )
        return attrs

    def _apply_gallery_changes(self, product, uploaded, remove_ids, order_ids):
        # products.signals deletes each removed photo's file.
        product.images.filter(id__in=remove_ids).delete()

        # New files go after the existing photos unless image_order says otherwise.
        last = product.images.aggregate(m=Max('order'))['m']
        next_order = 0 if last is None else last + 1
        created = [
            ProductImage.objects.create(product=product, image=f, order=next_order + offset)
            for offset, f in enumerate(uploaded)
        ]

        if order_ids is not None:
            existing = {str(p.id): p for p in product.images.exclude(id__in=[c.id for c in created])}
            new = {f'new-{n}': p for n, p in enumerate(created)}
            ordered = []
            for token in order_ids:
                # Only this product's photos can be placed; unknown ids are ignored.
                photo = existing.pop(token, None) or new.pop(token, None)
                if photo is not None:
                    ordered.append(photo)
            # Anything not listed keeps its relative place at the end.
            ordered += sorted(existing.values(), key=lambda p: (p.order, p.id)) + list(new.values())
            for index, photo in enumerate(ordered):
                photo.order = index
            ProductImage.objects.bulk_update(ordered, ['order'])

    def _pop_gallery_fields(self, validated_data):
        return (
            validated_data.pop('uploaded_images', []),
            validated_data.pop('remove_image_ids', []),
            validated_data.pop('image_order', None),
        )

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

    @transaction.atomic
    def create(self, validated_data):
        gallery = self._pop_gallery_fields(validated_data)
        sizes = validated_data.pop('sizes', None)
        validated_data.setdefault('slug', self._unique_slug(validated_data['name']))
        product = super().create(validated_data)
        self._apply_gallery_changes(product, *gallery)
        self._apply_sizes(product, sizes)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        gallery = self._pop_gallery_fields(validated_data)
        sizes = validated_data.pop('sizes', None)
        if 'name' in validated_data and 'slug' not in validated_data:
            validated_data['slug'] = self._unique_slug(validated_data['name'], pk=instance.pk)
        product = super().update(instance, validated_data)
        self._apply_gallery_changes(product, *gallery)
        self._apply_sizes(product, sizes)
        # Drop any prefetched (now stale) gallery/sizes so the response shows the change.
        getattr(product, '_prefetched_objects_cache', {}).pop('images', None)
        getattr(product, '_prefetched_objects_cache', {}).pop('variants', None)
        return product
