from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

CSRF_TRUSTED_ORIGINS = [o for o in config('CSRF_TRUSTED_ORIGINS', default='').split(',') if o]
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'anymail',
    # local
    'users',
    'products',
    'orders',
    'cart',
    'moodboard',
    'payments',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'senario.middleware.AdminLoginThrottleMiddleware',
]

ROOT_URLCONF = 'senario.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'senario.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='db'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://redis:6379/0'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

AUTH_USER_MODEL = 'users.User'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon':     '200/day',
        'user':     '2000/day',
        'login':    '5/min',
        'register': '10/hour',
        'resend-verification': '5/hour',
    },
}

# 5 MB upload limit
DATA_UPLOAD_MAX_MEMORY_SIZE  = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE  = 5 * 1024 * 1024

# Security headers (active when DEBUG=False)
SECURE_BROWSER_XSS_FILTER       = True
SECURE_CONTENT_TYPE_NOSNIFF     = True
X_FRAME_OPTIONS                 = 'DENY'

# Cookies (admin session + CSRF) and transport hardening — nginx already
# redirects http->https and terminates TLS, but Django needs these too so
# the admin session/CSRF cookies are never sent unencrypted and HSTS is
# actually asserted to browsers.
if not DEBUG:
    SESSION_COOKIE_SECURE   = True
    CSRF_COOKIE_SECURE      = True
    SECURE_SSL_REDIRECT     = True
    SECURE_HSTS_SECONDS     = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD     = True

# nginx terminates TLS and forwards this header; without it Django can't tell
# a request arrived over HTTPS (breaks CSRF cookie security and absolute-URL
# generation, e.g. verification links, behind the proxy).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

from datetime import timedelta
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', default='http://localhost').split(',')

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Email / branding
BRAND_NAME = config('BRAND_NAME', default='Senario')
FRONTEND_URL = config('FRONTEND_URL', default='')  # e.g. https://senario.app — if unset, verification links hit the API directly
EMAIL_VERIFICATION_TIMEOUT_DAYS = config('EMAIL_VERIFICATION_TIMEOUT_DAYS', default=3, cast=int)
PASSWORD_RESET_TIMEOUT = EMAIL_VERIFICATION_TIMEOUT_DAYS * 24 * 60 * 60

EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend' if DEBUG else 'anymail.backends.resend.EmailBackend',
)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=f'{BRAND_NAME} <no-reply@senario.app>')
SUPPORT_EMAIL = config('SUPPORT_EMAIL', default='Senarioproject@gmail.com')

ANYMAIL = {
    'RESEND_API_KEY': config('RESEND_API_KEY', default=''),
}

# Viva.com (Smart Checkout) payments
# VIVA_ENV defaults to 'demo' so a misconfigured deploy fails safe into the
# sandbox rather than silently taking real payments.
VIVA_ENV = config('VIVA_ENV', default='demo')
VIVA_CLIENT_ID = config('VIVA_CLIENT_ID', default='')
VIVA_CLIENT_SECRET = config('VIVA_CLIENT_SECRET', default='')
VIVA_SOURCE_CODE = config('VIVA_SOURCE_CODE', default='')
VIVA_WEBHOOK_VERIFICATION_KEY = config('VIVA_WEBHOOK_VERIFICATION_KEY', default='')
