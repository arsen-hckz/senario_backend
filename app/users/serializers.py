import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import PendingRegistration

User = get_user_model()


class RegisterSerializer(serializers.Serializer):
    email      = serializers.EmailField()
    password   = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    last_name  = serializers.CharField(max_length=60, required=False, allow_blank=True)

    def validate_email(self, value):
        email = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return email

    def create(self, validated_data):
        pending, _ = PendingRegistration.objects.update_or_create(
            email=validated_data['email'],
            defaults={
                'password_hash': make_password(validated_data['password']),
                'first_name': validated_data.get('first_name', ''),
                'last_name': validated_data.get('last_name', ''),
                'token': secrets.token_urlsafe(32),
                'created_at': timezone.now(),
            },
        )
        return pending


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'is_staff', 'created_at')
        read_only_fields = ('id', 'email', 'is_staff', 'created_at')


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        try:
            data = super().validate(attrs)
        except AuthenticationFailed:
            email = attrs.get(self.username_field, '')
            if PendingRegistration.objects.filter(email__iexact=email).exists():
                raise AuthenticationFailed(
                    'Please verify your email address before logging in.', code='email_not_verified',
                )
            raise
        data['user'] = UserSerializer(self.user).data
        return data


class ResendVerificationEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
