import base64
import uuid
from decimal import ROUND_HALF_UP, Decimal

import requests
from django.conf import settings
from django.core.cache import cache

# Viva uses a hyphen before the environment subdomain for its API/auth hosts,
# but no hyphen for the customer-facing checkout page — verified against
# Viva's own developer docs, not guessed.
_ACCOUNTS_HOST = 'demo-accounts.vivapayments.com' if settings.VIVA_ENV == 'demo' else 'accounts.vivapayments.com'
_API_HOST = 'demo-api.vivapayments.com' if settings.VIVA_ENV == 'demo' else 'api.vivapayments.com'
_CHECKOUT_HOST = 'demo.vivapayments.com' if settings.VIVA_ENV == 'demo' else 'www.vivapayments.com'


def _token_cache_key():
    # Scoped to environment + client id: a token cached for the demo account
    # (or before a credential change) must never be sent to a different one.
    return f'viva:access_token:{settings.VIVA_ENV}:{settings.VIVA_CLIENT_ID}'


def to_cents(amount):
    """Currency amount (Decimal, or the float euros Viva's transaction API returns) -> integer cents.

    Viva is inconsistent here: order creation takes integer cents, but
    Retrieve Transaction returns `amount` as decimal euros (e.g. 30.0).
    Going through str() keeps floats like 19.99 from turning into 19.98999...
    """
    return int((Decimal(str(amount)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class VivaError(Exception):
    pass


def _fetch_access_token():
    credentials = base64.b64encode(
        f'{settings.VIVA_CLIENT_ID}:{settings.VIVA_CLIENT_SECRET}'.encode()
    ).decode()
    try:
        response = requests.post(
            f'https://{_ACCOUNTS_HOST}/connect/token',
            headers={
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            data={'grant_type': 'client_credentials'},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise VivaError(f'Could not reach Viva for an access token: {exc}') from exc
    if not response.ok:
        raise VivaError(f'Failed to obtain Viva access token: {response.status_code} {response.text}')

    payload = response.json()
    token = payload['access_token']
    # Refresh a little early so we never hand out a token that expires mid-request.
    cache.set(_token_cache_key(), token, timeout=max(payload.get('expires_in', 3600) - 60, 60))
    return token


def get_access_token():
    return cache.get(_token_cache_key()) or _fetch_access_token()


def _api_request(method, path, **kwargs):
    """Authenticated call to Viva's API; retries once with a fresh token on 401
    (token revoked or credentials rotated before our cached copy expired)."""
    for attempt in range(2):
        token = get_access_token() if attempt == 0 else _fetch_access_token()
        headers = {'Authorization': f'Bearer {token}'}
        try:
            response = requests.request(method, f'https://{_API_HOST}{path}', headers=headers, timeout=10, **kwargs)
        except requests.RequestException as exc:
            raise VivaError(f'Could not reach Viva ({method} {path}): {exc}') from exc
        if response.status_code != 401:
            return response
        cache.delete(_token_cache_key())
    return response


def create_order(*, amount_cents, customer_trns, merchant_trns, customer_email, customer_full_name):
    response = _api_request('POST', '/checkout/v2/orders', json={
        'amount': amount_cents,
        'customerTrns': customer_trns,
        'merchantTrns': merchant_trns,
        'sourceCode': settings.VIVA_SOURCE_CODE,
        'customer': {
            'email': customer_email,
            'fullName': customer_full_name,
            'requestLang': 'el-GR',
        },
    })
    if not response.ok:
        raise VivaError(f'Failed to create Viva order: {response.status_code} {response.text}')

    # Keep as a string: orderCode can exceed JS/JSON-safe integer precision.
    return str(response.json()['orderCode'])


def checkout_url(order_code):
    return f'https://{_CHECKOUT_HOST}/web/checkout?ref={order_code}'


def get_transaction(transaction_id):
    # The id comes from an unauthenticated webhook body and goes into a URL
    # we call with our own credentials — only ever let a real GUID through.
    try:
        transaction_id = str(uuid.UUID(str(transaction_id)))
    except ValueError as exc:
        raise VivaError(f'Not a Viva transaction id: {transaction_id!r}') from exc

    response = _api_request('GET', f'/checkout/v2/transactions/{transaction_id}')
    if not response.ok:
        raise VivaError(f'Failed to retrieve Viva transaction: {response.status_code} {response.text}')
    return response.json()
