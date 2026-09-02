from django.contrib.auth import get_user_model
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .emails import send_verification_email
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterSerializer,
    ResendVerificationEmailSerializer,
    UserSerializer,
)
from .throttles import LoginRateThrottle, RegisterRateThrottle, ResendVerificationRateThrottle
from .tokens import email_verification_token

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
        user = serializer.save()
        send_verification_email(user, request)
        return Response({
            'user': UserSerializer(user).data,
            'detail': 'Registration successful. Check your email to verify your account before logging in.',
        }, status=status.HTTP_201_CREATED)


class VerifyEmailView(APIView):
    permission_classes = (permissions.AllowAny,)

    def get(self, request, uidb64, token):
        user = self._get_user(uidb64)
        valid = user is not None and email_verification_token.check_token(user, token)

        if not valid:
            return Response(
                {'detail': 'This verification link is invalid or has expired.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=['is_email_verified'])

        return Response({'detail': 'Email verified successfully.'})

    @staticmethod
    def _get_user(uidb64):
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            return User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None


class ResendVerificationEmailView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = ResendVerificationEmailSerializer
    throttle_classes = [ResendVerificationRateThrottle]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(email__iexact=serializer.validated_data['email']).first()
        if user and not user.is_email_verified:
            send_verification_email(user, request)

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
