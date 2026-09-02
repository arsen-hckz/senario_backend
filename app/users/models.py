from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra):
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    email      = models.EmailField(unique=True)
    first_name = models.CharField(max_length=60, blank=True)
    last_name  = models.CharField(max_length=60, blank=True)
    is_active  = models.BooleanField(default=True)
    is_staff   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = []
    objects = UserManager()

    def __str__(self):
        return self.email


class PendingRegistration(models.Model):
    """An unverified signup. Promoted to a real User once the email link is clicked;
    never touches the users table before then, so the email isn't 'taken' by a
    signup nobody completed — a retry with the same address just refreshes this row."""
    email         = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=128)
    first_name    = models.CharField(max_length=60, blank=True)
    last_name     = models.CharField(max_length=60, blank=True)
    token         = models.CharField(max_length=64, unique=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email
