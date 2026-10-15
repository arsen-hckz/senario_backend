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
from orders.stock import decrement_order_stock, order_unavailable_items

from . import viva_client
from .models import Payment
from .viva_client import VivaError, VivaTransactionNotFound

logger = logging.getLogger(__name__)

# Viva webhook EventTypeId for "Transaction Payment Created".
TRANSACTION_PAYMENT_CREATED = 1796

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


class CreateCheckoutView(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = [CheckoutRateThrottle]

    def post(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id, user=request.user)

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
                customer_email=request.user.email,
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
        if not isinstance(request.data, dict) or request.data.get('EventTypeId') != TRANSACTION_PAYMENT_CREATED:
            # Only successful-payment events confirm orders. A reversal (refund)
            # event carries the same OrderCode, and must never count as payment.
            return Response(status=status.HTTP_200_OK)
        event_data = request.data.get('EventData') or {}
        order_code = str(event_data.get('OrderCode') or '')
        transaction_id = str(event_data.get('TransactionId') or '')
        if not order_code or not _is_guid(transaction_id):
            # Not an event shape we care about — ack so Viva doesn't retry it forever.
            return Response(status=status.HTTP_200_OK)

        payment = Payment.objects.filter(viva_order_code=order_code).first()
        if payment is None or payment.status != Payment.Status.PENDING:
            return Response(status=status.HTTP_200_OK)

        # Each delivery makes us call Viva; cap it per order code so a replayed
        # code can't hammer Viva's API. 429 is non-2xx, so Viva retries later.
        verify_key = f'viva-webhook-verify:{order_code}'
        cache.add(verify_key, 0, timeout=600)
        if cache.incr(verify_key) > WEBHOOK_VERIFY_LIMIT:
            logger.warning('Webhook verification limit hit for Viva order %s', order_code)
            return Response(status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Never trust the webhook body for the actual payment facts — Viva
        # doesn't sign these POSTs, so re-fetch the transaction ourselves
        # with our own OAuth credentials before believing anything.
        try:
            txn = viva_client.get_transaction(transaction_id)
        except VivaTransactionNotFound:
            # This endpoint is public and unthrottled, so anyone can post made-up
            # ids. Warning + 4xx only: an error log or a 5xx response would email
            # staff on every one. Still non-2xx, so Viva retries a real payment
            # it hadn't finished recording yet.
            logger.warning('Webhook for unknown Viva transaction %s', transaction_id)
            return Response(status=status.HTTP_404_NOT_FOUND)
        except VivaError:
            logger.exception('Failed to verify Viva transaction %s', transaction_id)
            # Non-2xx so Viva retries delivery later and we get another chance to verify.
            return Response(status=status.HTTP_502_BAD_GATEWAY)

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
