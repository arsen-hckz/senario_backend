import hashlib
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, viewsets
from rest_framework.response import Response

from .models import Category, Product
from .serializers import CategorySerializer, ProductSerializer

CACHE_TTL = 60 * 5  # 5 minutes


class ProductListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants')
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
    queryset = Product.objects.filter(is_active=True).select_related('category').prefetch_related('variants')


class CategoryListView(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = CategorySerializer
    queryset = Category.objects.all()


class ProductAdminViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = ProductSerializer
    queryset = Product.objects.all().select_related('category').prefetch_related('variants')
    lookup_field = 'pk'
    pagination_class = None

    def perform_create(self, serializer):
        serializer.save()
        cache.delete_pattern('products:*')

    def perform_update(self, serializer):
        serializer.save()
        cache.delete_pattern('products:*')

    def perform_destroy(self, instance):
        instance.delete()
        cache.delete_pattern('products:*')
