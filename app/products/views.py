import hashlib
from django.core.cache import cache
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer

CACHE_TTL = 60 * 5  # 5 minutes


class ProductListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants', 'images')
        category = self.request.query_params.get('category')
        search   = self.request.query_params.get('search')
        if category:
            qs = qs.filter(category__slug=category)
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def list(self, request, *args, **kwargs):
        # Keyed on the category only, never the raw URL or the search text:
        # those are unbounded, so `?x=1`, `?x=2`, ... would each add a Redis
        # entry and anyone could fill the cache. Searches skip the cache, and
        # an empty result (e.g. a made-up category) is never stored.
        search = request.query_params.get('search')
        category = request.query_params.get('category') or ''
        cache_key = None if search else 'products:category:' + hashlib.md5(category.encode()).hexdigest()

        if cache_key:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(cached)
        data = ProductSerializer(self.get_queryset(), many=True, context={'request': request}).data
        if cache_key and data:
            cache.set(cache_key, data, CACHE_TTL)
        return Response(data)


class ProductDetailView(generics.RetrieveAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = ProductSerializer
    lookup_field = 'slug'
    queryset = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants', 'images')


class CategoryListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = CategorySerializer
    queryset = Category.objects.all()


class ProductAdminViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = ProductSerializer
    queryset = Product.objects.all().select_related('category').prefetch_related('variants', 'images')
    lookup_field = 'pk'
    pagination_class = None
    # The public list cache is cleared by products.signals on every save/delete.

    def perform_create(self, serializer):
        # New products go to the end of the shop's list.
        max_position = Product.objects.aggregate(m=Max('position'))['m']
        serializer.save(position=0 if max_position is None else max_position + 1)


class ProductReorderView(APIView):
    """Sets the shop's product order. Takes {"order": [id, ...]}; products
    missing from the list keep their relative order after the listed ones."""
    permission_classes = (permissions.IsAdminUser,)

    def post(self, request):
        order = request.data.get('order')
        if not isinstance(order, list) or len(order) > 1000:
            return Response({'detail': 'order must be a list of product ids.'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            products = list(Product.objects.select_for_update().order_by('position', 'id'))
            by_id = {str(p.id): p for p in products}
            ordered = []
            for product_id in order:
                product = by_id.pop(str(product_id), None) if isinstance(product_id, (int, str)) else None
                if product is not None:
                    ordered.append(product)
            ordered += [p for p in products if str(p.id) in by_id]
            for index, product in enumerate(ordered):
                product.position = index
            Product.objects.bulk_update(ordered, ['position'])
            # bulk_update sends no post_save, so clear the public list cache here.
            transaction.on_commit(lambda: cache.delete_pattern('products:*'))

        qs = Product.objects.all().select_related('category').prefetch_related('variants', 'images')
        return Response(ProductSerializer(qs, many=True, context={'request': request}).data)
