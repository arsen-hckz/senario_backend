import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
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

    def validate(self, attrs):
        # Same strength rules the admin uses (common passwords, all-numeric,
        # too similar to the name/email) — min_length alone accepted "12345678".
        candidate = User(
            email=attrs['email'],
            first_name=attrs.get('first_name', ''),
            last_name=attrs.get('last_name', ''),
        )
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({'password': list(exc.messages)})
        return attrs

    def create(self, validated_data):
        existing = PendingRegistration.objects.filter(email__iexact=validated_data['email']).first()
        cutoff = timezone.now() - timedelta(days=settings.EMAIL_VERIFICATION_TIMEOUT_DAYS)
        if existing and existing.created_at >= cutoff:
            # A still-valid signup for this address exists: re-send its link
            # but never let a second signup replace its password. Otherwise
            # anyone could re-register a victim's address with their own
            # password, and the victim's click on the newest link would
            # create the account with the attacker's password.
            return existing

        data = {
            'email': validated_data['email'],
            'password_hash': make_password(validated_data['password']),
            'first_name': validated_data.get('first_name', ''),
            'last_name': validated_data.get('last_name', ''),
            'token': secrets.token_urlsafe(32),
            'created_at': timezone.now(),
        }
        if existing:
            for field, value in data.items():
                setattr(existing, field, value)
            existing.save()
            return existing
        return PendingRegistration.objects.create(**data)


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
