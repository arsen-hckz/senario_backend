from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework import status
from rest_framework.test import APITestCase

from products.models import Product
from .models import Order, OrderItem

User = get_user_model()


class AdminOrderStatusTests(APITestCase):
    """Stock is held while an order is confirmed/shipped/delivered; staff
    moving it in or out of that by hand takes or gives back stock."""

    def setUp(self):
        from products.models import ProductVariant
        staff = User.objects.create_user(email='staff@example.com', password='testpass123', is_staff=True)
        self.client.force_authenticate(user=staff)
        self.product = Product.objects.create(name='Hoodie', slug='hoodie', price=Decimal('50.00'), stock=0)
        self.variant = ProductVariant.objects.create(product=self.product, size='M', stock=5)
        self.order = Order.objects.create(
            user=staff, total=Decimal('100.00'), full_name='A', address='B', city='C', country='GR', postal_code='1',
        )
        OrderItem.objects.create(
            order=self.order, product=self.product, variant=self.variant,
            product_name='Hoodie', size='M', price=Decimal('50.00'), qty=2,
        )

    def set_status(self, value):
        res = self.client.patch(f'/api/orders/admin/{self.order.pk}/', {'status': value}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        self.variant.refresh_from_db()
        return res

    def test_confirming_by_hand_takes_stock_and_cancelling_gives_it_back(self):
        self.set_status('confirmed')
        self.assertEqual(self.variant.stock, 3)
        self.set_status('shipped')
        self.assertEqual(self.variant.stock, 3)
        res = self.set_status('cancelled')
        self.assertEqual(self.variant.stock, 5)
        self.assertFalse(res.data['refund_needed'])

    def test_orders_cannot_be_set_back_to_pending(self):
        # setUp's order is an old-style pending one: it may stay pending.
        self.set_status('pending')
        self.set_status('confirmed')
        res = self.client.patch(f'/api/orders/admin/{self.order.pk}/', {'status': 'pending'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual((self.order.status, self.variant.stock), (Order.Status.CONFIRMED, 3))

    def test_django_admin_refuses_pending_too(self):
        from django.core.exceptions import ValidationError
        self.order.full_clean()  # old pending order, unchanged: fine
        Order.objects.filter(pk=self.order.pk).update(status=Order.Status.CANCELLED)
        self.order.status = Order.Status.PENDING
        with self.assertRaises(ValidationError):
            self.order.full_clean()
        with self.assertRaises(ValidationError):
            Order(total=1, full_name='A', address='B', city='C', country='GR', postal_code='1').full_clean()

    def test_cancelling_a_viva_paid_order_flags_the_refund(self):
        from payments.models import Payment
        payment = Payment.objects.create(
            order=self.order, viva_order_code='123', amount=Decimal('100.00'), status=Payment.Status.PAID,
        )
        self.order.status = Order.Status.CONFIRMED
        self.order.save()
        self.variant.stock = 3
        self.variant.save()

        res = self.set_status('cancelled')
        self.assertTrue(res.data['refund_needed'])
        self.assertEqual(self.variant.stock, 5)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUND_NEEDED)

    def test_customers_cannot_change_status(self):
        self.client.force_authenticate(user=User.objects.create_user(email='c@example.com', password='testpass123'))
        res = self.client.patch(f'/api/orders/admin/{self.order.pk}/', {'status': 'confirmed'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 5)

    def test_django_admin_status_change_takes_stock_too(self):
        from django.contrib import admin as django_admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        from .admin import OrderAdmin

        request = RequestFactory().post('/admin/')
        request.session = {}
        request._messages = FallbackStorage(request)
        self.order.status = Order.Status.CONFIRMED
        OrderAdmin(Order, django_admin.site).save_model(request, self.order, None, True)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 3)


class ReceiptTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='buyer@example.com', password='testpass123')
        self.order = Order.objects.create(
            user=self.user, total=Decimal('100.00'), email='buyer@example.com', phone='+30 690 000 0000',
            full_name='Γιάννης Παπαδόπουλος', address='Ερμού 1', city='Αθήνα', country='GR', postal_code='10563',
        )
        OrderItem.objects.create(order=self.order, product_name='Black Tee', size='M', price=Decimal('50.00'), qty=2)

    def test_vat_split_adds_up_to_the_total(self):
        from .receipt import vat_breakdown
        self.assertEqual(vat_breakdown(Decimal('100.00')), (Decimal('80.65'), Decimal('19.35')))
        for total in ('0.01', '19.99', '24.50', '1234.56'):
            net, vat = vat_breakdown(Decimal(total))
            self.assertEqual(net + vat, Decimal(total))

    def test_pdf_receipt_renders_greek_text(self):
        from .receipt import build_receipt_pdf
        pdf = build_receipt_pdf(self.order, '11111111-1111-4111-8111-111111111111')
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertIn(b'DejaVuSans', pdf)  # embedded font that has Greek letters

    def test_admin_resend_action_emails_the_customer(self):
        from django.contrib import admin as django_admin
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.core import mail
        from django.test import RequestFactory
        from .admin import OrderAdmin

        request = RequestFactory().post('/admin/')
        request.session = {}
        request._messages = FallbackStorage(request)
        OrderAdmin(Order, django_admin.site).resend_confirmation(request, Order.objects.filter(pk=self.order.pk))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Γιάννης', mail.outbox[0].body)

    def test_order_items_include_the_product_photo(self):
        import tempfile
        from django.test import override_settings
        from products.models import ProductImage
        from moodboard.tests import make_png

        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            product = Product.objects.create(name='Black Tee', slug='black-tee', price=Decimal('50.00'))
            ProductImage.objects.create(product=product, image=make_png('tee.png'))
            self.order.items.update(product=product)
            self.client.force_authenticate(self.user)
            item = self.client.get('/api/orders/').data['results'][0]['items'][0]
        self.assertTrue(item['image'].startswith('http://testserver/media/products/'))
