from django.urls import path

from .views import CreateCheckoutView, VivaWebhookView

urlpatterns = [
    path('checkout/<int:order_id>/', CreateCheckoutView.as_view(), name='payments-checkout'),
    path('webhook/viva/',            VivaWebhookView.as_view(),    name='payments-webhook-viva'),
]
