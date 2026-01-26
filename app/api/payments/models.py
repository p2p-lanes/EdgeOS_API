from typing import TYPE_CHECKING, List

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.applications.models import Application
    from app.api.attendees.models import Attendee
    from app.api.products.models import Product


class PaymentProduct(Base):
    __tablename__ = 'payment_products'

    payment_id = Column(Integer, ForeignKey('payments.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    attendee_id = Column(Integer, ForeignKey('attendees.id'), primary_key=True)
    quantity = Column(Integer, default=1)

    product_name = Column(String)
    product_description = Column(String, nullable=True)
    product_price = Column(Float)
    product_category = Column(String)
    created_at = Column(DateTime, default=current_time)

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

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        unique=True,
        index=True,
    )
    payment_id = Column(Integer, ForeignKey('payments.id'), nullable=False)
    external_payment_id = Column(String, nullable=False)
    installment_number = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    paid_at = Column(DateTime, nullable=False)

    payment: Mapped['Payment'] = relationship('Payment', back_populates='installments')


class Payment(Base):
    __tablename__ = 'payments'

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        unique=True,
        index=True,
    )
    application_id = Column(Integer, ForeignKey('applications.id'), nullable=False)
    external_id = Column(String)
    status = Column(String)
    amount = Column(Float)
    currency = Column(String)
    rate = Column(Float)
    source = Column(String)
    checkout_url = Column(String)
    installments_total = Column(Integer)  # Plan length
    installments_paid = Column(Integer, default=0)
    is_installment_plan = Column(Boolean, default=False)
    coupon_code_id = Column(Integer, ForeignKey('coupon_codes.id'), nullable=True)
    coupon_code = Column(String, nullable=True)
    discount_value = Column(Float, nullable=True)
    edit_passes = Column(Boolean, default=False)
    group_id = Column(Integer, ForeignKey('groups.id'), nullable=True)

    application: Mapped['Application'] = relationship(
        'Application', back_populates='payments'
    )
    products_snapshot: Mapped[List['PaymentProduct']] = relationship(
        'PaymentProduct', back_populates='payment'
    )
    installments: Mapped[List['PaymentInstallment']] = relationship(
        'PaymentInstallment', back_populates='payment'
    )

    created_at = Column(DateTime, default=current_time)
    updated_at = Column(DateTime, default=current_time, onupdate=current_time)
