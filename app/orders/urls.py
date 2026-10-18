from django.urls import path
from .views import (
    AdminOrderListView, AdminOrderUpdateView, CreateOrderView, GuestOrderCreateView, GuestOrderDetailView,
    OrderDetailView, OrderListView, ShippingRuleView,
)

urlpatterns = [
    path('',                OrderListView.as_view(),          name='order-list'),
    path('create/',         CreateOrderView.as_view(),        name='order-create'),
    path('<int:pk>/',       OrderDetailView.as_view(),        name='order-detail'),
    path('guest/',          GuestOrderCreateView.as_view(),   name='order-guest-create'),
    path('guest/<int:pk>/', GuestOrderDetailView.as_view(),   name='order-guest-detail'),
    path('shipping/',       ShippingRuleView.as_view(),       name='order-shipping'),
    path('admin/',          AdminOrderListView.as_view(),     name='order-admin-list'),
    path('admin/<int:pk>/', AdminOrderUpdateView.as_view(),  name='order-admin-update'),
]
