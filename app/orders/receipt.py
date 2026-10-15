"""PDF order receipt attached to the order confirmation email.

An order summary for the customer, not a tax document: legal invoices in
Greece are issued through myDATA, which this does not do.
"""
import io
import os
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from xml.sax.saxutils import escape

# The built-in PDF fonts have no Greek letters, and customers often write
# their name and address in Greek. DejaVu (fonts-dejavu-core in the image)
# covers Greek; without it (e.g. a dev machine) fall back to Helvetica.
_FONT_DIR = '/usr/share/fonts/truetype/dejavu'
_fonts = None


def _font_names():
    global _fonts
    if _fonts is None:
        regular = os.path.join(_FONT_DIR, 'DejaVuSans.ttf')
        bold = os.path.join(_FONT_DIR, 'DejaVuSans-Bold.ttf')
        if os.path.exists(regular) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont('DejaVuSans', regular))
            pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold))
            _fonts = ('DejaVuSans', 'DejaVuSans-Bold')
        else:
            _fonts = ('Helvetica', 'Helvetica-Bold')
    return _fonts


CENT = Decimal('0.01')


def vat_breakdown(total):
    """(net, vat) for a VAT-inclusive total; net + vat == total exactly."""
    rate = Decimal(settings.VAT_RATE_PERCENT)
    net = (total * 100 / (100 + rate)).quantize(CENT, rounding=ROUND_HALF_UP)
    return net, total - net


def euro(amount):
    return f'€{amount:,.2f}'


def build_receipt_pdf(order, transaction_id=''):
    regular, bold = _font_names()
    styles = {
        'brand': ParagraphStyle('brand', fontName=bold, fontSize=20, leading=24),
        'h': ParagraphStyle('h', fontName=bold, fontSize=10, leading=14, textColor=colors.HexColor('#71717a')),
        'p': ParagraphStyle('p', fontName=regular, fontSize=10, leading=14),
        'bold': ParagraphStyle('bold', fontName=bold, fontSize=10, leading=14),
        'small': ParagraphStyle('small', fontName=regular, fontSize=8, leading=11, textColor=colors.HexColor('#71717a')),
    }

    def para(text, style='p'):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), styles[style])

    seller = '\n'.join(line.strip() for line in settings.BUSINESS_DETAILS.split('|') if line.strip())
    seller = '\n'.join(filter(None, [seller, settings.SUPPORT_EMAIL]))
    customer = '\n'.join(filter(None, [
        order.full_name, order.address, f'{order.postal_code} {order.city}', order.country,
        order.email, order.phone,
    ]))
    details = '\n'.join(filter(None, [
        f'Order #{order.pk}',
        f'Date: {order.created_at:%d/%m/%Y}',
        'Paid by card (Viva)' if transaction_id else '',
    ]))

    story = [
        para(settings.BRAND_NAME, 'brand'),
        para('Order receipt', 'h'),
        Spacer(1, 8 * mm),
        Table(
            [[para('From', 'h'), para('Ship to', 'h'), para('Order', 'h')],
             [para(seller), para(customer), para(details)]],
            colWidths=[56 * mm, 62 * mm, 47 * mm], hAlign='LEFT',
            style=TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]),
        ),
        Spacer(1, 10 * mm),
    ]

    rows = [[para('Item', 'h'), para('Size', 'h'), para('Qty', 'h'), para('Price', 'h'), para('Total', 'h')]]
    for item in order.items.all():
        rows.append([
            para(item.product_name), para(item.size or '—'), para(item.qty),
            para(euro(item.price)), para(euro(item.subtotal)),
        ])
    net, vat = vat_breakdown(order.total)
    rate = Decimal(settings.VAT_RATE_PERCENT).normalize()
    totals = [
        ('Net amount', euro(net)),
        (f'VAT {rate}%', euro(vat)),
        ('Total paid', euro(order.total)),
    ]
    first_total_row = len(rows)
    for n, (label, value) in enumerate(totals):
        style = 'bold' if n == len(totals) - 1 else 'p'
        rows.append(['', '', '', para(label, style), para(value, style)])
    last = len(rows) - 1

    story.append(Table(rows, colWidths=[73 * mm, 20 * mm, 14 * mm, 30 * mm, 28 * mm], hAlign='LEFT', style=TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('LINEBELOW', (0, 0), (-1, 0), 0.75, colors.black),
        ('LINEBELOW', (0, first_total_row - 1), (-1, first_total_row - 1), 0.5, colors.HexColor('#d4d4d8')),
        ('LINEABOVE', (3, last), (-1, last), 0.75, colors.black),
    ])))

    story += [
        Spacer(1, 12 * mm),
        para('Prices include VAT. This is an order confirmation, not a tax invoice.', 'small'),
        para(f'Payment reference: {transaction_id}', 'small') if transaction_id else Spacer(1, 0),
        para(f'Questions about your order? Reply to the confirmation email or write to {settings.SUPPORT_EMAIL}.', 'small'),
    ]

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, title=f'{settings.BRAND_NAME} order #{order.pk}',
        leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
    ).build(story)
    return buffer.getvalue()
