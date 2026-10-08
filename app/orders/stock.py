from products.models import Product, ProductVariant


def stock_row(product, variant):
    """The row that actually holds stock for a line: the variant if there is one, else the product."""
    return variant if variant is not None else product


def unavailable_items(lines):
    """Names of lines that can't currently be fulfilled.

    `lines` is an iterable of (name, product, variant, qty). A line is
    unavailable if its product was deleted or deactivated, or there isn't
    enough stock for the requested quantity.
    """
    problems = []
    for name, product, variant, qty in lines:
        if product is None or not product.is_active:
            problems.append(name)
            continue
        if stock_row(product, variant).stock < qty:
            problems.append(name)
    return problems


def order_unavailable_items(order):
    lines = [
        (item.product_name, item.product, item.variant, item.qty)
        for item in order.items.select_related('product', 'variant')
    ]
    return unavailable_items(lines)


def decrement_order_stock(order, logger):
    """Take an order's quantities off stock. Must run inside a transaction.

    Never lets stock go below zero: by the time this runs the customer has
    already been charged, so a shortfall (two people buying the last item
    at once) must not abort recording the payment — it's logged for staff
    to handle instead.
    """
    for item in order.items.all():
        if item.variant_id:
            row = ProductVariant.objects.select_for_update().filter(pk=item.variant_id).first()
        elif item.product_id:
            row = Product.objects.select_for_update().filter(pk=item.product_id).first()
        else:
            row = None
        if row is None:
            continue
        if row.stock < item.qty:
            logger.error(
                'Oversold: Order #%s wants %s x %s but only %s in stock',
                order.id, item.qty, item.product_name, row.stock,
            )
        row.stock = max(row.stock - item.qty, 0)
        row.save(update_fields=['stock'])
