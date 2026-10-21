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
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .emails import address_quota_ok, send_account_exists_email, send_password_reset_email, send_verification_email
from .models import PendingRegistration
from .serializers import (
    CustomTokenObtainPairSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    ResendVerificationEmailSerializer,
    UserSerializer,
)
from .throttles import (
    LoginRateThrottle,
    PasswordChangeRateThrottle,
    PasswordResetConfirmRateThrottle,
    PasswordResetRateThrottle,
    RegisterRateThrottle,
    ResendVerificationRateThrottle,
)

User = get_user_model()


def _set_password_and_sign_out_everywhere(user, password):
    """Must run inside a transaction. Blacklists every refresh token the
    user holds: whoever knew the old password may still have one. Access
    tokens expire within the hour."""
    user.set_password(password)
    user.save(update_fields=['password'])
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)


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
        email = serializer.validated_data['email']

        existing_user = User.objects.filter(email__iexact=email).first()
        if existing_user is not None:
            if address_quota_ok('register', email):
                send_account_exists_email(existing_user, request)
        else:
            pending = serializer.save()
            if address_quota_ok('register', email):
                send_verification_email(pending, request)

        # Identical response either way: see RegisterSerializer.validate_email.
        return Response({
            'email': email,
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
        if pending and address_quota_ok('verify', pending.email):
            pending.token = secrets.token_urlsafe(32)
            pending.created_at = timezone.now()
            pending.save(update_fields=['token', 'created_at'])
            send_verification_email(pending, request)

        # Always return a generic response so this endpoint can't be used to enumerate accounts.
        return Response({'detail': 'If that email is registered and unverified, a new link has been sent.'})


class PasswordResetRequestView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = PasswordResetRequestSerializer
    throttle_classes = [PasswordResetRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(email__iexact=serializer.validated_data['email'], is_active=True).first()
        if user is not None and user.has_usable_password() and address_quota_ok('reset', user.email):
            send_password_reset_email(user, request)

        # Generic either way so this can't be used to enumerate accounts.
        return Response({'detail': 'If an account exists for that email, a reset link has been sent.'})


class PasswordResetConfirmView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = PasswordResetConfirmSerializer
    throttle_classes = [PasswordResetConfirmRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']

        with transaction.atomic():
            # Changing the password also invalidates the reset token (it is
            # derived from the password hash), so the link is single-use.
            _set_password_and_sign_out_everywhere(user, serializer.validated_data['password'])

        return Response({'detail': 'Your password has been reset. You can now sign in.'})


class PasswordChangeView(generics.GenericAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = PasswordChangeSerializer
    throttle_classes = [PasswordChangeRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user

        with transaction.atomic():
            _set_password_and_sign_out_everywhere(user, serializer.validated_data['new_password'])

        # Every other device is signed out; this one gets a fresh pair so the
        # customer who just changed their password stays logged in here.
        refresh = RefreshToken.for_user(user)
        return Response({
            'detail': 'Your password has been changed.',
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })


class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class LogoutView(APIView):
    # The refresh token is the proof here. Requiring a live access token meant
    # a customer logging out after an idle hour never had their refresh token
    # revoked: it stayed usable for 30 days on that device.
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        refresh = request.data.get('refresh')
        if not refresh or not isinstance(refresh, str):
            return Response({'detail': 'refresh is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            pass
        return Response(status=status.HTTP_205_RESET_CONTENT)
