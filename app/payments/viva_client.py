import base64
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

_TOKEN_CACHE_KEY = 'viva:access_token'


def to_cents(amount):
    """Currency amount (Decimal, or the float euros Viva's transaction API returns) -> integer cents.

    Viva is inconsistent here: order creation takes integer cents, but
    Retrieve Transaction returns `amount` as decimal euros (e.g. 30.0).
    Going through str() keeps floats like 19.99 from turning into 19.98999...
    """
    return int((Decimal(str(amount)) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class VivaError(Exception):
    pass


def get_access_token():
    token = cache.get(_TOKEN_CACHE_KEY)
    if token:
        return token

    credentials = base64.b64encode(
        f'{settings.VIVA_CLIENT_ID}:{settings.VIVA_CLIENT_SECRET}'.encode()
    ).decode()
    response = requests.post(
        f'https://{_ACCOUNTS_HOST}/connect/token',
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        data={'grant_type': 'client_credentials'},
        timeout=10,
    )
    if not response.ok:
        raise VivaError(f'Failed to obtain Viva access token: {response.status_code} {response.text}')

    payload = response.json()
    token = payload['access_token']
    # Refresh a little early so we never hand out a token that expires mid-request.
    cache.set(_TOKEN_CACHE_KEY, token, timeout=max(payload.get('expires_in', 3600) - 60, 60))
    return token


def create_order(*, amount_cents, customer_trns, merchant_trns, customer_email, customer_full_name):
    response = requests.post(
        f'https://{_API_HOST}/checkout/v2/orders',
        headers={
            'Authorization': f'Bearer {get_access_token()}',
            'Content-Type': 'application/json',
        },
        json={
            'amount': amount_cents,
            'customerTrns': customer_trns,
            'merchantTrns': merchant_trns,
            'sourceCode': settings.VIVA_SOURCE_CODE,
            'customer': {
                'email': customer_email,
                'fullName': customer_full_name,
                'requestLang': 'el-GR',
            },
        },
        timeout=10,
    )
    if not response.ok:
        raise VivaError(f'Failed to create Viva order: {response.status_code} {response.text}')

    # Keep as a string: orderCode can exceed JS/JSON-safe integer precision.
    return str(response.json()['orderCode'])


def checkout_url(order_code):
    return f'https://{_CHECKOUT_HOST}/web/checkout?ref={order_code}'


def get_transaction(transaction_id):
    response = requests.get(
        f'https://{_API_HOST}/checkout/v2/transactions/{transaction_id}',
        headers={'Authorization': f'Bearer {get_access_token()}'},
        timeout=10,
    )
    if not response.ok:
        raise VivaError(f'Failed to retrieve Viva transaction: {response.status_code} {response.text}')
    return response.json()
