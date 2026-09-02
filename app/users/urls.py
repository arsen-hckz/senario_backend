from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView,
    ProfileView,
    CustomTokenObtainPairView,
    LogoutView,
    VerifyEmailView,
    ResendVerificationEmailView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(),             name='auth-register'),
    path('login/',    CustomTokenObtainPairView.as_view(), name='auth-login'),
    path('refresh/',  TokenRefreshView.as_view(),         name='auth-refresh'),
    path('profile/',  ProfileView.as_view(),              name='auth-profile'),
    path('logout/',   LogoutView.as_view(),                name='auth-logout'),
    path('verify-email/<uidb64>/<token>/', VerifyEmailView.as_view(),           name='auth-verify-email'),
    path('resend-verification/',           ResendVerificationEmailView.as_view(), name='auth-resend-verification'),
]
