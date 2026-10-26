from django.urls import path

from .views import CheckoutStatusView, CreateCheckoutView, GuestCheckoutView, VivaWebhookView

urlpatterns = [
    path('checkout/',                   CreateCheckoutView.as_view(), name='payments-checkout'),
    path('guest-checkout/',             GuestCheckoutView.as_view(),  name='payments-guest-checkout'),
    path('checkout/<int:checkout_id>/', CheckoutStatusView.as_view(), name='payments-checkout-status'),
    path('webhook/viva/',               VivaWebhookView.as_view(),    name='payments-webhook-viva'),
]
