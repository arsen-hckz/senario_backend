import hmac

from django.http import Http404
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from users.throttles import _PerIPRateThrottle
from .models import Order
from .serializers import GuestOrderSerializer, OrderSerializer, CreateOrderSerializer, OrderStatusSerializer
from .shipping import shipping_rule
from .status import apply_status_change


class OrderListView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related('items__product__images').order_by('-created_at')


class OrderDetailView(generics.RetrieveAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = OrderSerializer

    def get_object(self):
        return get_object_or_404(Order, pk=self.kwargs['pk'], user=self.request.user)


class CreateOrderRateThrottle(UserRateThrottle):
    # Nobody places 20 orders an hour; past that it's a script filling the
    # orders table (and the staff order list) with pending orders.
    scope = 'order-create'


class CreateOrderView(generics.CreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CreateOrderSerializer
    throttle_classes = [CreateOrderRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save(user=request.user)
        return Response(OrderSerializer(order, context={'request': request}).data, status=status.HTTP_201_CREATED)


def guest_order_or_404(request, pk, queryset=None):
    """The guest order `pk`, if the request carries its secret in the
    X-Order-Token header. Account orders are never reachable this way."""
    token = request.headers.get('X-Order-Token', '')
    qs = Order.objects.all() if queryset is None else queryset
    order = qs.filter(pk=pk).exclude(access_token='').first()
    if order is None or not token or not hmac.compare_digest(order.access_token, token):
        raise Http404
    return order


class GuestOrderRateThrottle(_PerIPRateThrottle):
    scope = 'guest-order'


class GuestOrderCreateView(generics.CreateAPIView):
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    serializer_class = GuestOrderSerializer
    throttle_classes = [GuestOrderRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save()
        data = OrderSerializer(order, context={'request': request}).data
        # Shown once: the browser keeps it to pay and to check the order.
        data['access_token'] = order.access_token
        return Response(data, status=status.HTTP_201_CREATED)


class GuestOrderDetailView(generics.RetrieveAPIView):
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    serializer_class = OrderSerializer

    def get_object(self):
        return guest_order_or_404(self.request, self.kwargs['pk'], Order.objects.prefetch_related('items__product__images'))


class ShippingRuleView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request):
        return Response(shipping_rule())


class AdminOrderListView(generics.ListAPIView):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = OrderSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Order.objects.prefetch_related('items__product__images').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class AdminOrderUpdateView(generics.UpdateAPIView):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = OrderStatusSerializer
    queryset = Order.objects.all()
    http_method_names = ('patch',)

    def update(self, request, *args, **kwargs):
        with transaction.atomic():
            # Locked like the payment webhook does, so a payment arriving
            # mid-change can't take or give back stock twice.
            order = get_object_or_404(Order.objects.select_for_update(), pk=kwargs['pk'])
            old_status = order.status
            serializer = self.get_serializer(order, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            refund_needed = apply_status_change(order, old_status)
        return Response(dict(serializer.data, refund_needed=refund_needed))
