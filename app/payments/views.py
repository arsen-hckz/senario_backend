import logging

from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from orders.models import Order
from products.models import Product, ProductVariant

from . import viva_client
from .models import Payment
from .viva_client import VivaError

logger = logging.getLogger(__name__)


class CreateCheckoutView(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, order_id):
        order = get_object_or_404(Order, pk=order_id, user=request.user)

        if order.payments.filter(status=Payment.Status.PAID).exists():
            return Response(
                {'detail': 'This order has already been paid.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

    def get(self, request):
        # One-time URL ownership check Viva's merchant portal performs
        # before it will register this endpoint for event delivery.
        return Response({'Key': settings.VIVA_WEBHOOK_VERIFICATION_KEY})

    def post(self, request):
        event_data = request.data.get('EventData') or {}
        order_code = str(event_data.get('OrderCode') or '')
        transaction_id = event_data.get('TransactionId')
        if not order_code or not transaction_id:
            # Not an event shape we care about — ack so Viva doesn't retry it forever.
            return Response(status=status.HTTP_200_OK)

        payment = Payment.objects.filter(viva_order_code=order_code).first()
        if payment is None or payment.status == Payment.Status.PAID:
            return Response(status=status.HTTP_200_OK)

        # Never trust the webhook body for the actual payment facts — Viva
        # doesn't sign these POSTs, so re-fetch the transaction ourselves
        # with our own OAuth credentials before believing anything.
        try:
            txn = viva_client.get_transaction(transaction_id)
        except VivaError:
            logger.exception('Failed to verify Viva transaction %s', transaction_id)
            # Non-2xx so Viva retries delivery later and we get another chance to verify.
            return Response(status=status.HTTP_502_BAD_GATEWAY)

        verified = (
            txn.get('statusId') == 'F'
            and str(txn.get('orderCode') or '') == payment.viva_order_code
            and txn.get('amount') == viva_client.to_cents(payment.amount)
        )
        if not verified:
            return Response(status=status.HTTP_200_OK)

        with db_transaction.atomic():
            locked_payment = Payment.objects.select_for_update().get(pk=payment.pk)
            if locked_payment.status == Payment.Status.PAID:
                return Response(status=status.HTTP_200_OK)

            locked_payment.status = Payment.Status.PAID
            locked_payment.viva_transaction_id = str(transaction_id)
            locked_payment.save(update_fields=['status', 'viva_transaction_id', 'updated_at'])

            order = locked_payment.order
            if order.status == Order.Status.PENDING:
                order.status = Order.Status.CONFIRMED
                order.save(update_fields=['status', 'updated_at'])

            for item in order.items.all():
                if item.variant_id:
                    ProductVariant.objects.filter(pk=item.variant_id).update(stock=F('stock') - item.qty)
                elif item.product_id:
                    Product.objects.filter(pk=item.product_id).update(stock=F('stock') - item.qty)

        return Response(status=status.HTTP_200_OK)
