from django.urls import path
from .views import OrderListView, OrderDetailView, CreateOrderView, AdminOrderListView, AdminOrderUpdateView

urlpatterns = [
    path('',                OrderListView.as_view(),          name='order-list'),
    path('create/',         CreateOrderView.as_view(),        name='order-create'),
    path('<int:pk>/',       OrderDetailView.as_view(),        name='order-detail'),
    path('admin/',          AdminOrderListView.as_view(),     name='order-admin-list'),
    path('admin/<int:pk>/', AdminOrderUpdateView.as_view(),  name='order-admin-update'),
]
