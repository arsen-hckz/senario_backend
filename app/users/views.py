import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .emails import send_verification_email
from .models import PendingRegistration
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    ResendVerificationEmailSerializer,
    UserSerializer,
)
from .throttles import LoginRateThrottle, RegisterRateThrottle, ResendVerificationRateThrottle

User = get_user_model()


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    throttle_classes = [LoginRateThrottle]


class RegisterView(generics.CreateAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterSerializer
    throttle_classes = [RegisterRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pending = serializer.save()
        send_verification_email(pending, request)
        return Response({
            'email': pending.email,
            'detail': 'Registration successful. Check your email to verify your account before logging in.',
        }, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request, token):
        cutoff = timezone.now() - timedelta(days=settings.EMAIL_VERIFICATION_TIMEOUT_DAYS)

        with transaction.atomic():
            # Row lock: a double-click (or a mail scanner prefetching the link)
            # waits here, then finds the row gone instead of crashing on a
            # duplicate user.
            pending = (
                PendingRegistration.objects.select_for_update()
                .filter(token=token, created_at__gte=cutoff).first()
            )
            if pending is None:
                return Response(
                    {'detail': 'This verification link is invalid or has expired.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if User.objects.filter(email__iexact=pending.email).exists():
                pending.delete()
                return Response(
                    {'detail': 'This email is already verified. Please log in.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            User.objects.create(
                email=pending.email,
                first_name=pending.first_name,
                last_name=pending.last_name,
                password=pending.password_hash,
            )
            pending.delete()

        return Response({'detail': 'Email verified successfully.'})


class ResendVerificationEmailView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = ResendVerificationEmailSerializer
    throttle_classes = [ResendVerificationRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pending = PendingRegistration.objects.filter(email__iexact=serializer.validated_data['email']).first()
        if pending:
            pending.token = secrets.token_urlsafe(32)
            pending.created_at = timezone.now()
            pending.save(update_fields=['token', 'created_at'])
            send_verification_email(pending, request)

        # Always return a generic response so this endpoint can't be used to enumerate accounts.
        return Response({'detail': 'If that email is registered and unverified, a new link has been sent.'})


class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class LogoutView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh:
            return Response({'detail': 'refresh is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)
