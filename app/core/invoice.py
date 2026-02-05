import base64
import io
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse
from urllib.request import urlopen

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape

from app.api.payments import models


# ---- Helpers ----
def format_date(dt: datetime | None) -> str:
    # Match your formatDate; tweak to taste
    if dt is None:
        return ''
    return dt.strftime('%Y-%m-%d')


def format_money(value: float | None) -> str:
    # Backward-compatible wrapper; defaults to 2 decimals
    if value is None:
        return '0,00'
    return _format_money(value, 2)


def _format_money(value: float, decimals: int) -> str:
    # Simple money format (avoid locale quirks); allow custom decimals
    fmt = f'{{value:,.{decimals}f}}'
    s = fmt.format(value=value)
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


def is_crypto_currency(code: str) -> bool:
    return code.upper() in ('BTC', 'ETH')


def format_currency(value: float | None, currency: str | None) -> str:
    if value is None:
        return '0,00'
    decimals = 8 if currency and is_crypto_currency(currency) else 2
    return _format_money(value, decimals)


class CroppedImageFitWidth(Flowable):
    """Draw an image at full available width and crop vertically to the given box height.

    The image maintains its aspect ratio. If its scaled height exceeds the box height,
    the overflow is clipped (no stretching).
    """

    def __init__(self, image_source, width: float, height: float):
        super().__init__()
        self.reader = ImageReader(image_source)
        self.box_w = width
        self.box_h = height
        # flowable's own size equals the clipping box
        self.width = width
        self.height = height

    def draw(self) -> None:
        canvas = self.canv
        iw, ih = self.reader.getSize()
        if iw == 0:
            return
        # Scale proportionally to fill the full width
        scale = self.box_w / float(iw)
        draw_w = self.box_w
        draw_h = ih * scale
        dx = 0
        # Center vertically inside the clipping box; negative dy will crop top/bottom
        dy = (self.box_h - draw_h) / 2.0

        canvas.saveState()
        path = canvas.beginPath()
        path.rect(0, 0, self.box_w, self.box_h)
        canvas.clipPath(path, stroke=0)
        canvas.drawImage(self.reader, dx, dy, width=draw_w, height=draw_h, mask='auto')
        canvas.restoreState()


def generate_invoice_pdf(
    payment: models.Payment,
    client_name: str,
    discount: Optional[float] = None,  # percent (e.g., 10 for 10%)
    header_image: Optional[str] = None,  # URL or local path to header image
) -> str:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f'Invoice {payment.id}',
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name='Header',
            fontName='Helvetica-Bold',
            fontSize=16,
            alignment=1,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(name='Body', fontName='Helvetica', fontSize=12, leading=14)
    )
    styles.add(ParagraphStyle(name='Right', parent=styles['Body'], alignment=2))
    styles.add(
        ParagraphStyle(name='Bold', parent=styles['Body'], fontName='Helvetica-Bold')
    )

    flow: List[Flowable] = []

    if header_image:
        try:
            parsed = urlparse(header_image)
            if parsed.scheme in ('http', 'https'):
                with urlopen(header_image) as resp:  # nosec - trusted configured input
                    image_bytes = resp.read()
                source = io.BytesIO(image_bytes)
            else:
                source = header_image

            box_h = 46 * mm
            img_flowable = CroppedImageFitWidth(source, width=doc.width, height=box_h)
            flow.append(img_flowable)
            flow.append(Spacer(1, 6))
        except Exception:
            # Continue without header image if it fails to load
            pass

    # Header (title)
    flow.append(Paragraph('Invoice', styles['Header']))
    flow.append(Spacer(1, 6))

    # Two-column header (seller on left, invoice meta on right)
    left = [
        Paragraph('Edge Institute Inc', styles['Body']),
        Paragraph('Address: 1300 S 6th St, Austin, TX 78704', styles['Body']),
        Paragraph('Email: syl@edgecity.live', styles['Body']),
    ]
    right = [
        Paragraph(f'Date: {format_date(payment.created_at)}', styles['Right']),
        Paragraph(f'Invoice #: {payment.id}', styles['Right']),
        Paragraph(f'Bill to: {client_name}', styles['Right']),
    ]

    # Build as a 2-col table
    header_tbl = Table(
        [[left, right]],
        colWidths=[doc.width / 2, doc.width / 2],
        style=TableStyle(
            [
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]
        ),
    )
    flow.append(header_tbl)
    flow.append(Spacer(1, 12))

    # ---- Table header (conditional columns) ----
    # Columns: Quantity | Description | Unit Price | (Discount?) | (Rate?) | Amount
    headers = ['Quantity', 'Description', 'Unit Price']
    show_discount = discount is not None
    if show_discount:
        headers.append('Discount')
    rate = payment.rate or 1.0
    show_rate = rate > 1
    if show_rate:
        headers.append('Rate')
    headers.append('Amount')

    table_data = [headers]

    popup_name = payment.application.popup_city.name
    # ---- Table rows ----
    currency = payment.currency or 'USD'
    for item in payment.products_snapshot:
        # Unit price shown in original currency logic:
        # Your TS code shows unit price in original product_price (USD), and rate column if rate>1.
        # For the final amount, you convert to payment.currency and apply discount if any.
        unit_price_usd = float(item.product_price or 0)
        qty = int(item.quantity or 1)
        product_name = item.product_name or ''

        # If currency is not USD, show conversion via Rate column and compute amount in payment.currency
        if show_rate:
            # Convert unit to payment.currency: unit_in_currency = USD / rate
            unit_in_currency = unit_price_usd / rate
            total_unit = unit_in_currency * qty
            total_after_discount = total_unit * (1 - (discount or 0) / 100)
            desc_text = f'{product_name} - {popup_name}'
            desc_para = Paragraph(escape(desc_text), styles['Body'])
            row = [str(qty), desc_para, f'{format_money(unit_price_usd)} USD']
            if show_discount:
                row.append(f'{discount:.0f}%')
            row.append(f'1 {currency} = {format_money(rate)} USD')
            row.append(f'{format_currency(total_after_discount, currency)} {currency}')
        else:
            # Currency is USD or 1:1; keep it simple
            total_unit = unit_price_usd * qty
            total_after_discount = total_unit * (1 - (discount or 0) / 100)
            desc_para = Paragraph(escape(product_name), styles['Body'])
            row = [str(qty), desc_para, f'{format_money(unit_price_usd)} USD']
            if show_discount:
                row.append(f'{discount:.0f}%')
            row.append(f'{format_currency(total_after_discount, currency)} {currency}')
        table_data.append(row)

    # ---- Column widths: auto for non-description, description fills remaining ----
    # Index mapping given headers: [Qty, Desc, Unit, (Disc?), (Rate?), Amount]
    qty_idx = 0
    unit_idx = 2
    # Determine indices for optional columns
    idx = 3
    discount_idx = idx if show_discount else None
    if show_discount:
        idx += 1
    rate_idx = idx if show_rate else None
    if show_rate:
        idx += 1
    amount_idx = idx

    # Minimum widths (mm) to keep columns readable
    qty_min = 12 * mm
    unit_min = 24 * mm
    amount_min = 28 * mm
    discount_min = 16 * mm
    rate_min = 36 * mm
    desc_min = 30 * mm

    # Measure max content widths for non-description columns using font size 10
    def measure(text: str, bold: bool = False) -> float:
        font = 'Helvetica-Bold' if bold else 'Helvetica'
        return stringWidth(text, font, 10)

    # Start with header widths
    max_qty = measure(headers[qty_idx], bold=True)
    max_unit = measure(headers[unit_idx], bold=True)
    max_amount = measure(headers[-1], bold=True)  # last is Amount
    max_discount = (
        measure(headers[discount_idx], bold=True) if discount_idx is not None else 0
    )
    max_rate = measure(headers[rate_idx], bold=True) if rate_idx is not None else 0

    # Include body rows
    for row in table_data[1:]:
        max_qty = max(max_qty, measure(str(row[qty_idx])))
        max_unit = max(max_unit, measure(str(row[unit_idx])))
        max_amount = max(max_amount, measure(str(row[amount_idx])))
        if discount_idx is not None:
            max_discount = max(max_discount, measure(str(row[discount_idx])))
        if rate_idx is not None:
            max_rate = max(max_rate, measure(str(row[rate_idx])))

    # Add paddings (left+right = 8) and tiny buffer
    pad = 8 + 2
    qty_w = max(qty_min, max_qty + pad)
    unit_w = max(unit_min, max_unit + pad)
    amount_w = max(amount_min, max_amount + pad)
    discount_w = (
        max(discount_min, max_discount + pad) if discount_idx is not None else 0
    )
    rate_w = max(rate_min, max_rate + pad) if rate_idx is not None else 0

    other_sum = qty_w + unit_w + amount_w + discount_w + rate_w
    desc_w = doc.width - other_sum
    if desc_w < desc_min:
        # Scale down other columns proportionally to leave at least desc_min
        if other_sum <= 0:
            desc_w = doc.width
        else:
            target_other = max(doc.width - desc_min, doc.width * 0.6)
            scale = target_other / other_sum
            qty_w *= scale
            unit_w *= scale
            amount_w *= scale
            if discount_idx is not None:
                discount_w *= scale
            if rate_idx is not None:
                rate_w *= scale
            other_sum = qty_w + unit_w + amount_w + discount_w + rate_w
            desc_w = max(desc_min, doc.width - other_sum)

    col_widths = [qty_w, desc_w, unit_w]
    if discount_idx is not None:
        col_widths.append(discount_w)
    if rate_idx is not None:
        col_widths.append(rate_w)
    col_widths.append(amount_w)

    # ---- Table styling ----
    tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(
        TableStyle(
            [
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeeee')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('WORDWRAP', (1, 1), (1, -1), 'CJK'),
            ]
        )
    )
    flow.append(tbl)
    flow.append(Spacer(1, 12))

    # ---- Footer total ----
    # payment.amount is in USD; convert to display currency if needed
    amount = payment.amount or 0.0
    total = amount / rate if rate > 1 else amount
    total_par = Paragraph(
        f'<b>Total: {format_currency(total, currency)} {currency}</b>',
        styles['Bold'],
    )
    flow.append(total_par)

    # Build the document
    doc.build(flow)

    pdf_bytes = buffer.getvalue()
    return base64.b64encode(pdf_bytes).decode('ascii')
