from django.urls import path
from .views import ProductListView, ProductDetailView, CategoryListView, ProductAdminViewSet

admin_list   = ProductAdminViewSet.as_view({'get': 'list',   'post': 'create'})
admin_detail = ProductAdminViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

urlpatterns = [
    path('',                    ProductListView.as_view(),  name='product-list'),
    path('categories/',         CategoryListView.as_view(), name='category-list'),
    path('admin/',              admin_list,                 name='product-admin-list'),
    path('admin/<int:pk>/',     admin_detail,               name='product-admin-detail'),
    path('<slug:slug>/',        ProductDetailView.as_view(), name='product-detail'),
]
