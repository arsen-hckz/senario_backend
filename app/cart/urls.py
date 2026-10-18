from django.urls import path
from .views import CartItemView, CartQuoteView, CartView

urlpatterns = [
    path('',             CartView.as_view(),          name='cart'),
    path('quote/',       CartQuoteView.as_view(),     name='cart-quote'),
    path('<int:item_id>/', CartItemView.as_view(),    name='cart-item'),
]
