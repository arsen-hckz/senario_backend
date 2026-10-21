from django.urls import path

from .views import PageTextAdminView, PageTextView

urlpatterns = [
    path('admin/<slug:page>/', PageTextAdminView.as_view(), name='content-admin'),
    path('<slug:page>/',       PageTextView.as_view(),      name='content-page'),
]
