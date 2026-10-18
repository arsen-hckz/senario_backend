"""Item lists sent by the browser: a guest's cart lives in localStorage, so
every quote and guest order re-reads products, prices and stock from the
database and trusts nothing but the ids and quantities."""
import secrets
from dataclasses import dataclass

from django.db import transaction

from products.models import Product, ProductVariant
from .models import Order, OrderItem
from .shipping import shipping_for
from .stock import stock_row

MAX_QTY = 99
MAX_LINES = 50


class BadItems(ValueError):
    pass


@dataclass
class Line:
    product: Product
    variant: ProductVariant | None
    qty: int
    problem: str = ''

    @property
    def key(self):
        return f'{self.product.pk}-{self.variant.pk if self.variant else 0}'

    @property
    def subtotal(self):
        return self.product.effective_price * self.qty


def _positive_int(raw, maximum=None):
    if isinstance(raw, bool):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 1 or (maximum is not None and value > maximum):
        return None
    return value


def resolve_items(raw):
    """[{product_id, variant_id?, qty}] -> (lines, dropped).

    Raises BadItems for a malformed list. `dropped` counts entries whose
    product is gone, hidden, or whose size no longer exists; each remaining
    line has `problem` set when it can't be bought as it stands.
    """
    if not isinstance(raw, list) or len(raw) > MAX_LINES:
        raise BadItems(f'items must be a list of up to {MAX_LINES} items.')

    wanted = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise BadItems('Each item must be an object.')
        product_id = _positive_int(entry.get('product_id'))
        raw_variant = entry.get('variant_id')
        variant_id = _positive_int(raw_variant) if raw_variant not in (None, '', 0) else None
        qty = _positive_int(entry.get('qty', 1), MAX_QTY)
        if product_id is None or qty is None or (raw_variant not in (None, '', 0) and variant_id is None):
            raise BadItems(f'Each item needs a product_id, an optional variant_id and a qty from 1 to {MAX_QTY}.')
        key = (product_id, variant_id)
        wanted[key] = min(wanted.get(key, 0) + qty, MAX_QTY)

    products = {
        p.pk: p for p in Product.objects.filter(pk__in={pid for pid, _ in wanted}, is_active=True)
        .select_related('category').prefetch_related('variants', 'images')
    }
    lines, dropped = [], 0
    for (product_id, variant_id), qty in wanted.items():
        product = products.get(product_id)
        variants = {v.pk: v for v in product.variants.all()} if product else {}
        variant = variants.get(variant_id) if variant_id else None
        if product is None or (variant_id and variant is None):
            dropped += 1
            continue
        line = Line(product, variant, qty)
        if variant is None and variants:
            line.problem = 'Please choose a size.'
        else:
            available = stock_row(product, variant).stock
            if available < qty:
                line.problem = f'Only {available} left in stock.' if available else 'Sold out.'
        lines.append(line)
    return lines, dropped


def create_order(lines, details, user=None):
    """An order for `lines` (products already checked). Guest orders
    (no user) get a secret `access_token` instead of an owner."""
    with transaction.atomic():
        subtotal = sum(line.subtotal for line in lines)
        shipping = shipping_for(subtotal)
        order = Order.objects.create(
            user=user,
            access_token='' if user else secrets.token_urlsafe(32),
            total=subtotal + shipping,
            shipping=shipping,
            **details,
        )
        OrderItem.objects.bulk_create([
            OrderItem(
                order=order,
                product=line.product,
                variant=line.variant,
                product_name=line.product.name,
                size=line.variant.size if line.variant else '',
                price=line.product.effective_price,
                qty=line.qty,
            )
            for line in lines
        ])
    return order
