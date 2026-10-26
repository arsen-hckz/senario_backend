import hmac
import logging
import uuid

from django.conf import settings
from django.core.cache import cache
from django.db import transaction as db_transaction
from django.http import Http404
from rest_framework import permissions, status
from rest_framework.throttling import UserRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.emails import send_order_confirmation
from orders.models import Order
from orders.serializers import CheckoutSerializer, GuestCheckoutSerializer
from orders.status import apply_status_change
from orders.stock import decrement_order_stock
from users.throttles import _PerIPRateThrottle

from . import viva_client
from .checkout import create_paid_order, open_checkout
from .models import Checkout, Payment
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


def start_payment(checkout):
    """A Viva payment page for `checkout`, or an error Response. On an error
    the checkout is deleted: nothing was charged and the cart is untouched."""
    try:
        order_code = viva_client.create_order(
            amount_cents=viva_client.to_cents(checkout.total),
            customer_trns=f'{settings.BRAND_NAME} order',
            merchant_trns=f'Checkout {checkout.pk}',
            customer_email=checkout.email,
            customer_full_name=checkout.full_name,
        )
    except VivaError:
        logger.exception('Failed to create Viva checkout order for Checkout #%s', checkout.pk)
        checkout.delete()
        return Response(
            {'detail': 'Could not start checkout. Please try again.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    Payment.objects.create(checkout=checkout, viva_order_code=order_code, amount=checkout.total)
    return Response({
        'checkout_id': checkout.pk,
        'token': checkout.token,
        'checkout_url': viva_client.checkout_url(order_code),
    }, status=status.HTTP_201_CREATED)


class CreateCheckoutView(APIView):
    """Signed in: pay for the server-side cart. No order exists until Viva
    confirms the payment, and the cart is only emptied then."""
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = [CheckoutRateThrottle]

    def post(self, request):
        serializer = CheckoutSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        lines = data.pop('items')
        checkout = open_checkout(lines, serializer.details(data), user=request.user)
        return start_payment(checkout)


class GuestCheckoutRateThrottle(_PerIPRateThrottle):
    scope = 'guest-checkout'


class GuestCheckoutView(APIView):
    """No account: pay for the items in the browser's cart."""
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = [GuestCheckoutRateThrottle]

    def post(self, request):
        serializer = GuestCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        lines = data.pop('items')
        checkout = open_checkout(lines, serializer.details(data))
        return start_payment(checkout)


class CheckoutStatusView(APIView):
    """What the return page polls: has the checkout become an order yet?
    Opened with the checkout's secret in the X-Checkout-Token header."""
    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)

    def get(self, request, checkout_id):
        token = request.headers.get('X-Checkout-Token', '')
        checkout = Checkout.objects.select_related('order').filter(pk=checkout_id).first()
        if checkout is None or not token or not hmac.compare_digest(checkout.token, token):
            raise Http404
        order = checkout.order
        return Response({
            'paid': order is not None,
            'order_id': order.pk if order else None,
            'order_status': order.status if order else None,
            # A guest order opens with this same token; account orders are in My Orders.
            'is_guest': checkout.user_id is None,
        })


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
            locked_payment.viva_transaction_id = str(transaction_id)
            if locked_payment.order_id is None:
                order = self._order_for_checkout(locked_payment)
            else:
                order = self._confirm_pending_order(locked_payment)
            if order is None:
                return Response(status=status.HTTP_200_OK)

            locked_payment.status = Payment.Status.PAID
            locked_payment.order = order
            locked_payment.save(update_fields=['status', 'order', 'viva_transaction_id', 'updated_at'])

            # After commit: only email once the payment is really recorded.
            db_transaction.on_commit(lambda: send_order_confirmation(order, locked_payment.viva_transaction_id))

        return Response(status=status.HTTP_200_OK)

    def _flag_refund(self, payment, reason, *args):
        """The money was taken but no order can be confirmed for it."""
        payment.status = Payment.Status.REFUND_NEEDED
        payment.save(update_fields=['status', 'viva_transaction_id', 'updated_at'])
        logger.error('Payment #%s needs a refund: ' + reason, payment.pk, *args)

    def _order_for_checkout(self, payment):
        """The new confirmed Order for the payment's checkout, or None
        (the payment is then flagged for a refund)."""
        checkout = Checkout.objects.select_for_update().filter(pk=payment.checkout_id).first()
        if checkout is None:
            self._flag_refund(payment, 'its checkout no longer exists (Viva order %s)', payment.viva_order_code)
            return None
        if checkout.order_id is not None:
            self._flag_refund(payment, 'Checkout #%s was already paid as Order #%s', checkout.pk, checkout.order_id)
            return None
        return create_paid_order(checkout, logger)

    def _confirm_pending_order(self, payment):
        """Payments started before checkouts existed were taken against a
        pending Order: confirm it, or None (the payment is flagged for a refund)."""
        # Lock the order too, so two payments for the same order (customer
        # paid in two tabs) are processed one at a time.
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        other_paid = order.payments.filter(status=Payment.Status.PAID).exclude(pk=payment.pk).exists()
        if other_paid or order.status != Order.Status.PENDING:
            # Already paid or cancelled — don't confirm twice or take stock again.
            self._flag_refund(payment, 'Order #%s (status %s) was already paid or not pending', order.pk, order.status)
            return None
        order.status = Order.Status.CONFIRMED
        order.save(update_fields=['status', 'updated_at'])
        decrement_order_stock(order, logger)
        return order

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
            logger.warning('Partial Viva refund %s on Payment #%s (%s of %s): order left as is',
                           transaction_id, payment.pk, txn['amount'], payment.amount)
            return Response(status=status.HTTP_200_OK)

        with db_transaction.atomic():
            locked_payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if locked_payment.status not in (Payment.Status.PAID, Payment.Status.REFUND_NEEDED):
                return Response(status=status.HTTP_200_OK)
            locked_payment.status = Payment.Status.REFUNDED
            locked_payment.save(update_fields=['status', 'updated_at'])
            if locked_payment.order_id is None:
                # Money that never became an order (see _flag_refund): nothing else to undo.
                return Response(status=status.HTTP_200_OK)

            order = Order.objects.select_for_update().get(pk=locked_payment.order_id)
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
