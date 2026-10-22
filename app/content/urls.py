from django.urls import path

from .views import PageImageAdminView, PageImageView, PageTextAdminView, PageTextView

urlpatterns = [
    path('admin/<slug:page>/images/',            PageImageAdminView.as_view(), name='content-admin-images'),
    path('admin/<slug:page>/images/<slug:key>/', PageImageAdminView.as_view(), name='content-admin-image'),
    path('admin/<slug:page>/',                   PageTextAdminView.as_view(),  name='content-admin'),
    path('<slug:page>/images/',                  PageImageView.as_view(),      name='content-page-images'),
    path('<slug:page>/',                         PageTextView.as_view(),       name='content-page'),
]
