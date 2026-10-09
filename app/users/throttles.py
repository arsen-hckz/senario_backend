from rest_framework.throttling import SimpleRateThrottle


class _PerIPRateThrottle(SimpleRateThrottle):
    """Limits a single endpoint per client IP, logged in or not.

    Deliberately not ScopedRateThrottle: that class ignores a `scope` set on
    the subclass and only reads `throttle_scope` from the view, so these
    limits silently never applied.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class LoginRateThrottle(_PerIPRateThrottle):
    scope = 'login'


class RegisterRateThrottle(_PerIPRateThrottle):
    scope = 'register'


class ResendVerificationRateThrottle(_PerIPRateThrottle):
    scope = 'resend-verification'


class PasswordResetRateThrottle(_PerIPRateThrottle):
    scope = 'password-reset'


class PasswordResetConfirmRateThrottle(_PerIPRateThrottle):
    scope = 'password-reset-confirm'
