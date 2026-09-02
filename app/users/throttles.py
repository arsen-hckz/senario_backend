from rest_framework.throttling import ScopedRateThrottle


class LoginRateThrottle(ScopedRateThrottle):
    scope = 'login'


class RegisterRateThrottle(ScopedRateThrottle):
    scope = 'register'


class ResendVerificationRateThrottle(ScopedRateThrottle):
    scope = 'resend-verification'
