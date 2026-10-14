from django.urls import path

from .views import SalePostAdminViewSet, SalePostListView, SalePostReorderView

admin_list   = SalePostAdminViewSet.as_view({'get': 'list', 'post': 'create'})
admin_detail = SalePostAdminViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

urlpatterns = [
    path('',                SalePostListView.as_view(),    name='post-list'),
    path('admin/',          admin_list,                    name='post-admin-list'),
    path('admin/reorder/',  SalePostReorderView.as_view(), name='post-admin-reorder'),
    path('admin/<int:pk>/', admin_detail,                  name='post-admin-detail'),
]
