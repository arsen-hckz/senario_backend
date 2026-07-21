from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .models import Order
from .serializers import OrderSerializer, CreateOrderSerializer, OrderStatusSerializer


class OrderListView(generics.ListAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = OrderSerializer

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related('items').order_by('-created_at')


class OrderDetailView(generics.RetrieveAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = OrderSerializer

    def get_object(self):
        return get_object_or_404(Order, pk=self.kwargs['pk'], user=self.request.user)


class CreateOrderView(generics.CreateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = CreateOrderSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.save(user=request.user)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class AdminOrderListView(generics.ListAPIView):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = OrderSerializer
    pagination_class = None

    def get_queryset(self):
        qs = Order.objects.prefetch_related('items').order_by('-created_at')
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class AdminOrderUpdateView(generics.UpdateAPIView):
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = OrderStatusSerializer
    queryset = Order.objects.all()
    http_method_names = ('patch',)
