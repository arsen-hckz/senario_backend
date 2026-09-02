from django.urls import path

from .views import MoodboardListView, MoodboardAdminViewSet, MoodboardReorderView

admin_list   = MoodboardAdminViewSet.as_view({'get': 'list', 'post': 'create'})
admin_detail = MoodboardAdminViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

urlpatterns = [
    path('',                MoodboardListView.as_view(),  name='moodboard-list'),
    path('admin/',          admin_list,                   name='moodboard-admin-list'),
    path('admin/reorder/',  MoodboardReorderView.as_view(), name='moodboard-admin-reorder'),
    path('admin/<int:pk>/', admin_detail,                 name='moodboard-admin-detail'),
]
