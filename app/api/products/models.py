from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.attendees.models import Attendee, AttendeeProduct
    from app.api.payments.models import PaymentProduct


class Product(Base):
    __tablename__ = 'products'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    name: Mapped[str]
    slug: Mapped[str]
    price: Mapped[float]
    compare_price: Mapped[float | None]
    popup_city_id: Mapped[int] = mapped_column(ForeignKey('popups.id'), index=True)
    description: Mapped[str | None]
    category: Mapped[str | None]
    attendee_category: Mapped[str | None]
    start_date: Mapped[datetime | None]
    end_date: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(default=True)
    exclusive: Mapped[bool] = mapped_column(default=False)
    insurance_percentage: Mapped[float | None]
    min_price: Mapped[float | None]
    max_price: Mapped[float | None]

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

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]
