from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.stock import stock_row
from products.models import Product, ProductVariant
from .models import Cart, CartItem
from .serializers import CartSerializer

MAX_QTY_PER_ITEM = 99


def _parse_qty(raw, minimum):
    """Integer qty from request data, or None if it's not a whole number in range."""
    try:
        qty = int(raw)
    except (TypeError, ValueError):
        return None
    if qty < minimum or qty > MAX_QTY_PER_ITEM:
        return None
    return qty


def _bad_qty():
    return Response(
        {'detail': f'qty must be a whole number up to {MAX_QTY_PER_ITEM}.'},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _not_enough_stock(item_stock):
    return Response(
        {'detail': f'Only {item_stock} left in stock.'},
        status=status.HTTP_400_BAD_REQUEST,
    )


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
        qty = _parse_qty(request.data.get('qty', 1), minimum=1)
        if qty is None:
            return _bad_qty()

        product = get_object_or_404(Product, pk=product_id, is_active=True)
        variant = get_object_or_404(ProductVariant, pk=variant_id, product=product) if variant_id else None

        item = CartItem.objects.filter(cart=cart, product=product, variant=variant).first()
        new_qty = qty + (item.qty if item else 0)
        if new_qty > MAX_QTY_PER_ITEM:
            return _bad_qty()
        available = stock_row(product, variant).stock
        if new_qty > available:
            return _not_enough_stock(available)

        if item:
            item.qty = new_qty
            item.save()
        else:
            CartItem.objects.create(cart=cart, product=product, variant=variant, qty=qty)

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
        # 0 (or below) removes the item, same as before.
        try:
            raw = int(request.data.get('qty', 1))
        except (TypeError, ValueError):
            return _bad_qty()
        if raw <= 0:
            item.delete()
            return Response(CartSerializer(cart).data)

        qty = _parse_qty(raw, minimum=1)
        if qty is None:
            return _bad_qty()
        available = stock_row(item.product, item.variant).stock
        if qty > available:
            return _not_enough_stock(available)

        item.qty = qty
        item.save()
        return Response(CartSerializer(cart).data)
