from django.urls import path

from .views import CreateCheckoutView, GuestCheckoutView, VivaWebhookView

urlpatterns = [
    path('checkout/<int:order_id>/', CreateCheckoutView.as_view(), name='payments-checkout'),
    path('guest-checkout/<int:order_id>/', GuestCheckoutView.as_view(), name='payments-guest-checkout'),
    path('webhook/viva/',            VivaWebhookView.as_view(),    name='payments-webhook-viva'),
]
