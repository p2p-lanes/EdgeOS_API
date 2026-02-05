from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.applications.models import Application
    from app.api.attendees.models import Attendee
    from app.api.products.models import Product


class PaymentProduct(Base):
    __tablename__ = 'payment_products'

    payment_id: Mapped[int] = mapped_column(ForeignKey('payments.id'), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), primary_key=True)
    attendee_id: Mapped[int] = mapped_column(
        ForeignKey('attendees.id'), primary_key=True
    )
    quantity: Mapped[int | None] = mapped_column(default=1)

    product_name: Mapped[str | None]
    product_description: Mapped[str | None]
    product_price: Mapped[float | None]
    product_category: Mapped[str | None]
    insurance_applied: Mapped[bool | None] = mapped_column(default=False)
    insurance_price: Mapped[float | None]
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)

    attendee: Mapped['Attendee'] = relationship(
        'Attendee', back_populates='payment_products'
    )
    payment: Mapped['Payment'] = relationship(
        'Payment', back_populates='products_snapshot'
    )
    product: Mapped['Product'] = relationship(
        'Product', back_populates='payment_products'
    )


class PaymentInstallment(Base):
    __tablename__ = 'payment_installments'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey('payments.id'))
    external_payment_id: Mapped[str]
    installment_number: Mapped[int]
    amount: Mapped[float]
    currency: Mapped[str]
    paid_at: Mapped[datetime]

    payment: Mapped['Payment'] = relationship('Payment', back_populates='installments')


class Payment(Base):
    __tablename__ = 'payments'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey('applications.id'))
    external_id: Mapped[str | None]
    status: Mapped[str | None]
    amount: Mapped[float | None]
    currency: Mapped[str | None]
    rate: Mapped[float | None]
    source: Mapped[str | None]
    checkout_url: Mapped[str | None]
    installments_total: Mapped[int | None]  # Plan length
    installments_paid: Mapped[int | None] = mapped_column(default=0)
    is_installment_plan: Mapped[bool | None] = mapped_column(default=False)
    coupon_code_id: Mapped[int | None] = mapped_column(ForeignKey('coupon_codes.id'))
    coupon_code: Mapped[str | None]
    discount_value: Mapped[float | None]
    edit_passes: Mapped[bool | None] = mapped_column(default=False)
    group_id: Mapped[int | None] = mapped_column(ForeignKey('groups.id'))

    application: Mapped['Application'] = relationship(
        'Application', back_populates='payments'
    )
    products_snapshot: Mapped[List['PaymentProduct']] = relationship(
        'PaymentProduct', back_populates='payment'
    )
    installments: Mapped[List['PaymentInstallment']] = relationship(
        'PaymentInstallment', back_populates='payment'
    )

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
