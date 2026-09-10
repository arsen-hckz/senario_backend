from django.core.cache import cache
from django.http import HttpResponse


class AdminLoginThrottleMiddleware:
    """Rate-limits POST attempts to the Django admin login form per client IP.

    The DRF API login endpoint already has ScopedRateThrottle; the admin
    site's own login form has no such protection by default.

    Trusts X-Real-IP as set by nginx. This is only safe because
    docker-compose never publishes the web service's port to the host —
    nginx is the sole entrypoint, so this header can't be spoofed by
    reaching Django directly. If that topology ever changes, this needs
    to validate the request actually came through a trusted proxy first.
    """
    RATE_LIMIT = 5
    WINDOW_SECONDS = 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/admin/login/' and request.method == 'POST':
            ip = request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', 'unknown')
            key = f'admin-login-throttle:{ip}'
            attempts = cache.get(key, 0)
            if attempts >= self.RATE_LIMIT:
                return HttpResponse('Too many login attempts. Please try again later.', status=429)
            cache.set(key, attempts + 1, self.WINDOW_SECONDS)
        return self.get_response(request)
