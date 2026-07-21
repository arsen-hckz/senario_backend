from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from products.models import Product, ProductVariant
from .models import Cart, CartItem
from .serializers import CartSerializer


class CartView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def _get_cart(self, user):
        cart, _ = Cart.objects.get_or_create(user=user)
        return cart

    def get(self, request):
        cart = self._get_cart(request.user)
        return Response(CartSerializer(cart).data)

    def post(self, request):
        cart = self._get_cart(request.user)
        product_id = request.data.get('product_id')
        variant_id = request.data.get('variant_id')
        qty = int(request.data.get('qty', 1))

        product = get_object_or_404(Product, pk=product_id, is_active=True)
        variant = get_object_or_404(ProductVariant, pk=variant_id, product=product) if variant_id else None

        item, created = CartItem.objects.get_or_create(
            cart=cart, product=product, variant=variant,
            defaults={'qty': qty}
        )
        if not created:
            item.qty += qty
            item.save()

        return Response(CartSerializer(cart).data, status=status.HTTP_200_OK)

    def delete(self, request):
        cart = self._get_cart(request.user)
        item_id = request.data.get('item_id')
        get_object_or_404(CartItem, pk=item_id, cart=cart).delete()
        return Response(CartSerializer(cart).data)


class CartItemView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def patch(self, request, item_id):
        cart = get_object_or_404(Cart, user=request.user)
        item = get_object_or_404(CartItem, pk=item_id, cart=cart)
        qty = int(request.data.get('qty', 1))
        if qty <= 0:
            item.delete()
        else:
            item.qty = qty
            item.save()
        return Response(CartSerializer(cart).data)
