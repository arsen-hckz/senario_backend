from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import RegisterView, ProfileView, CustomTokenObtainPairView, LogoutView

urlpatterns = [
    path('register/', RegisterView.as_view(),             name='auth-register'),
    path('login/',    CustomTokenObtainPairView.as_view(), name='auth-login'),
    path('refresh/',  TokenRefreshView.as_view(),         name='auth-refresh'),
    path('profile/',  ProfileView.as_view(),              name='auth-profile'),
    path('logout/',   LogoutView.as_view(),                name='auth-logout'),
]
