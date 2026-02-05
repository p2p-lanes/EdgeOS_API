from typing import TYPE_CHECKING, List

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.attendees.models import Attendee, AttendeeProduct
    from app.api.payments.models import PaymentProduct


class Product(Base):
    __tablename__ = 'products'

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        unique=True,
        index=True,
    )
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    compare_price = Column(Float)
    popup_city_id = Column(Integer, ForeignKey('popups.id'), index=True, nullable=False)
    description = Column(String)
    category = Column(String)
    attendee_category = Column(String)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    is_active = Column(Boolean, nullable=False, default=True)
    exclusive = Column(Boolean, nullable=False, default=False)
    insurance_percentage = Column(Float, nullable=True)
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint(
            'insurance_percentage IS NULL OR insurance_percentage > 0',
            name='ck_products_insurance_percentage_positive',
        ),
        CheckConstraint(
            'min_price IS NULL OR min_price > 0',
            name='ck_products_min_price_positive',
        ),
        CheckConstraint(
            'max_price IS NULL OR max_price > 0',
            name='ck_products_max_price_positive',
        ),
        CheckConstraint(
            'max_price IS NULL OR min_price IS NULL OR max_price >= min_price',
            name='ck_products_max_gte_min_price',
        ),
    )

    attendees: Mapped[List['Attendee']] = relationship(
        'Attendee',
        secondary='attendee_products',
        back_populates='products',
        viewonly=True,
    )
    attendee_products: Mapped[List['AttendeeProduct']] = relationship(
        'AttendeeProduct', back_populates='product'
    )
    payment_products: Mapped[List['PaymentProduct']] = relationship(
        'PaymentProduct', back_populates='product'
    )

    created_at = Column(DateTime, default=current_time)
    updated_at = Column(DateTime, default=current_time, onupdate=current_time)
    created_by = Column(String)
    updated_by = Column(String)
