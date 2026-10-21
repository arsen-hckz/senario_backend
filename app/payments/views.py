import logging
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction as db_transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.throttling import UserRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.emails import send_order_confirmation
from orders.models import Order
from orders.status import apply_status_change
from orders.views import guest_order_or_404
from users.throttles import _PerIPRateThrottle
from orders.stock import decrement_order_stock, order_unavailable_items

from . import viva_client
from .models import Payment
from .viva_client import VivaError, VivaTransactionNotFound

logger = logging.getLogger(__name__)

# Viva webhook EventTypeIds: "Transaction Payment Created" and
# "Transaction Reversal Created" (a refund or void went through).
TRANSACTION_PAYMENT_CREATED = 1796
TRANSACTION_REVERSAL_CREATED = 1797

# Viva TransactionTypeIds that give money back: card refund, card void,
# wallet refund, card refund (installments). A reversal webhook only counts
# if Viva says the transaction it names is one of these, so a charge's own
# id posted as a "reversal" can't cancel a paid order.
REFUND_TRANSACTION_TYPES = {4, 7, 11, 18}

# A checkout started this recently is handed out again instead of creating
# another Viva order: a double click or a quick retry shouldn't leave a trail
# of abandoned payment attempts. Well inside the checkout page's lifetime.
REUSE_CHECKOUT_FOR = timedelta(minutes=5)

# Verification calls to Viva per order code per 10 minutes. Real deliveries
# need one or two; past that it's someone replaying their own order code.
WEBHOOK_VERIFY_LIMIT = 10


class CheckoutRateThrottle(UserRateThrottle):
    scope = 'checkout'


def _is_guid(value):
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def start_checkout(order, customer_email):
    """A Viva checkout URL for `order`, or an error Response."""
    if order.payments.filter(status=Payment.Status.PAID).exists():
        return Response(
            {'detail': 'This order has already been paid.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if order.status != Order.Status.PENDING:
        return Response(
            {'detail': 'This order can no longer be paid.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    unavailable = order_unavailable_items(order)
    if unavailable:
        return Response(
            {'detail': 'Some items are no longer available: ' + ', '.join(unavailable)},
            status=status.HTTP_409_CONFLICT,
        )

    recent = order.payments.filter(
        status=Payment.Status.PENDING, created_at__gte=timezone.now() - REUSE_CHECKOUT_FOR,
    ).first()
    if recent is not None:
        return Response({'checkout_url': viva_client.checkout_url(recent.viva_order_code)})

    try:
        order_code = viva_client.create_order(
            amount_cents=viva_client.to_cents(order.total),
            customer_trns=f'Order #{order.id} — {settings.BRAND_NAME}',
            merchant_trns=str(order.id),
            customer_email=customer_email,
            customer_full_name=order.full_name,
        )
    except VivaError:
        logger.exception('Failed to create Viva checkout order for Order #%s', order.id)
        return Response(
            {'detail': 'Could not start checkout. Please try again.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    Payment.objects.create(order=order, viva_order_code=order_code, amount=order.total)

    return Response({'checkout_url': viva_client.checkout_url(order_code)})


class CreateCheckoutView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = [CheckoutRateThrottle]

    def post(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id, user=request.user)
        return start_checkout(order, request.user.email)


class GuestCheckoutRateThrottle(_PerIPRateThrottle):
    scope = 'guest-checkout'


class GuestCheckoutView(APIView):
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = [GuestCheckoutRateThrottle]

    def post(self, request, order_id):
        order = guest_order_or_404(request, order_id)
        return start_checkout(order, order.email)


class VivaWebhookView(APIView):
    permission_classes = (permissions.AllowAny,)
    # Every delivery comes from Viva's handful of IPs; the anon rate limit
    # would start rejecting real payment notifications on a busy day.
    throttle_classes = ()

    def get(self, request):
        # One-time URL ownership check Viva's merchant portal performs
        # before it will register this endpoint for event delivery.
        return Response({'Key': settings.VIVA_WEBHOOK_VERIFICATION_KEY})

    def post(self, request):
        event_type = request.data.get('EventTypeId') if isinstance(request.data, dict) else None
        if event_type not in (TRANSACTION_PAYMENT_CREATED, TRANSACTION_REVERSAL_CREATED):
            return Response(status=status.HTTP_200_OK)
        event_data = request.data.get('EventData') or {}
        if not isinstance(event_data, dict):
            return Response(status=status.HTTP_200_OK)
        order_code = str(event_data.get('OrderCode') or '')
        transaction_id = str(event_data.get('TransactionId') or '')
        if not order_code or not _is_guid(transaction_id):
            # Not an event shape we care about — ack so Viva doesn't retry it forever.
            return Response(status=status.HTTP_200_OK)

        payment = Payment.objects.filter(viva_order_code=order_code).first()
        if event_type == TRANSACTION_PAYMENT_CREATED:
            wanted = (Payment.Status.PENDING,)
        else:
            # A refund only matters for money we took (refund_needed: staff
            # cancelled the order first and the alert asked them to refund).
            wanted = (Payment.Status.PAID, Payment.Status.REFUND_NEEDED)
        if payment is None or payment.status not in wanted or transaction_id == payment.viva_transaction_id:
            return Response(status=status.HTTP_200_OK)

        txn, error = self._fetch_transaction(order_code, transaction_id)
        if error is not None:
            return error
        if event_type == TRANSACTION_REVERSAL_CREATED:
            return self._record_refund(payment, transaction_id, txn)

        verified = (
            txn.get('statusId') == 'F'
            and str(txn.get('orderCode') or '') == payment.viva_order_code
            and txn.get('amount') is not None
            and viva_client.to_cents(txn['amount']) == viva_client.to_cents(payment.amount)
        )
        if not verified:
            return Response(status=status.HTTP_200_OK)

        with db_transaction.atomic():
            locked_payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if locked_payment.status != Payment.Status.PENDING:
                return Response(status=status.HTTP_200_OK)
            # Lock the order too, so two payments for the same order (customer
            # paid in two tabs) are processed one at a time.
            order = Order.objects.select_for_update().get(pk=locked_payment.order_id)
            locked_payment.viva_transaction_id = str(transaction_id)

            other_paid = order.payments.filter(status=Payment.Status.PAID).exclude(pk=locked_payment.pk).exists()
            if other_paid or order.status != Order.Status.PENDING:
                # The money was taken, but this order is already paid or was
                # cancelled — flag it for a manual refund rather than
                # confirming twice or decrementing stock again.
                locked_payment.status = Payment.Status.REFUND_NEEDED
                locked_payment.save(update_fields=['status', 'viva_transaction_id', 'updated_at'])
                logger.error(
                    'Payment #%s for Order #%s (status %s) needs a refund: order already paid or not pending',
                    locked_payment.pk, order.pk, order.status,
                )
                return Response(status=status.HTTP_200_OK)

            locked_payment.status = Payment.Status.PAID
            locked_payment.save(update_fields=['status', 'viva_transaction_id', 'updated_at'])

            order.status = Order.Status.CONFIRMED
            order.save(update_fields=['status', 'updated_at'])

            decrement_order_stock(order, logger)

            # After commit: only email once the payment is really recorded.
            db_transaction.on_commit(lambda: send_order_confirmation(order, locked_payment.viva_transaction_id))

        return Response(status=status.HTTP_200_OK)

    def _fetch_transaction(self, order_code, transaction_id):
        """(transaction, None), or (None, the Response to send)."""
        # Each delivery makes us call Viva; cap it per order code so a replayed
        # code can't hammer Viva's API. 429 is non-2xx, so Viva retries later.
        verify_key = f'viva-webhook-verify:{order_code}'
        cache.add(verify_key, 0, timeout=600)
        if cache.incr(verify_key) > WEBHOOK_VERIFY_LIMIT:
            logger.warning('Webhook verification limit hit for Viva order %s', order_code)
            return None, Response(status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Never trust the webhook body for the actual payment facts — Viva
        # doesn't sign these POSTs, so re-fetch the transaction ourselves
        # with our own OAuth credentials before believing anything.
        try:
            return viva_client.get_transaction(transaction_id), None
        except VivaTransactionNotFound:
            # This endpoint is public and unthrottled, so anyone can post made-up
            # ids. Warning + 4xx only: an error log or a 5xx response would email
            # staff on every one. Still non-2xx, so Viva retries a real payment
            # it hadn't finished recording yet.
            logger.warning('Webhook for unknown Viva transaction %s', transaction_id)
            return None, Response(status=status.HTTP_404_NOT_FOUND)
        except VivaError:
            logger.exception('Failed to verify Viva transaction %s', transaction_id)
            # Non-2xx so Viva retries delivery later and we get another chance to verify.
            return None, Response(status=status.HTTP_502_BAD_GATEWAY)

    def _record_refund(self, payment, transaction_id, txn):
        """A verified full refund marks the payment refunded and cancels a
        confirmed order (giving its stock back). Anything else is left for staff."""
        try:
            type_id = int(txn.get('transactionTypeId'))
        except (TypeError, ValueError):
            type_id = None
        if (
            txn.get('statusId') != 'F'
            or str(txn.get('orderCode') or '') != payment.viva_order_code
            or type_id not in REFUND_TRANSACTION_TYPES
            or txn.get('amount') is None
        ):
            logger.warning('Ignored Viva reversal %s for order code %s: not a completed refund of it',
                           transaction_id, payment.viva_order_code)
            return Response(status=status.HTTP_200_OK)

        if abs(viva_client.to_cents(txn['amount'])) != viva_client.to_cents(payment.amount):
            # Partial refund: the order may still be (partly) going out — staff decide.
            logger.warning('Partial Viva refund %s on Order #%s (%s of %s): order left as is',
                           transaction_id, payment.order_id, txn['amount'], payment.amount)
            return Response(status=status.HTTP_200_OK)

        with db_transaction.atomic():
            locked_payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if locked_payment.status not in (Payment.Status.PAID, Payment.Status.REFUND_NEEDED):
                return Response(status=status.HTTP_200_OK)
            order = Order.objects.select_for_update().get(pk=locked_payment.order_id)
            locked_payment.status = Payment.Status.REFUNDED
            locked_payment.save(update_fields=['status', 'updated_at'])

            if order.status in (Order.Status.PENDING, Order.Status.CONFIRMED):
                old_status = order.status
                order.status = Order.Status.CANCELLED
                order.save(update_fields=['status', 'updated_at'])
                apply_status_change(order, old_status)  # gives the stock back
                logger.warning('Order #%s cancelled: refunded in full in Viva', order.pk)
            elif order.status != Order.Status.CANCELLED:
                # Shipped or delivered: whether the stock comes back depends on the return.
                logger.warning('Order #%s (%s) was refunded in full in Viva: update it by hand',
                               order.pk, order.status)

        return Response(status=status.HTTP_200_OK)
