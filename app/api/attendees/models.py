from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.applications.models import Application
    from app.api.payments.models import PaymentProduct
    from app.api.products.models import Product


class AttendeeProduct(Base):
    __tablename__ = 'attendee_products'

    attendee_id: Mapped[int] = mapped_column(
        ForeignKey('attendees.id'), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), primary_key=True)
    quantity: Mapped[int] = mapped_column(default=1)
    insurance_applied: Mapped[bool | None] = mapped_column(default=False)
    insurance_price: Mapped[float | None]

    attendee: Mapped['Attendee'] = relationship(
        'Attendee', back_populates='attendee_products'
    )
    product: Mapped['Product'] = relationship(
        'Product', back_populates='attendee_products'
    )


class Attendee(Base):
    __tablename__ = 'attendees'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey('applications.id'))
    name: Mapped[str]
    category: Mapped[str]
    email: Mapped[str | None]
    gender: Mapped[str | None]
    poap_url: Mapped[str | None]
    check_in_code: Mapped[str]

    application: Mapped['Application'] = relationship(
        'Application', back_populates='attendees'
    )
    attendee_products: Mapped[List['AttendeeProduct']] = relationship(
        'AttendeeProduct', back_populates='attendee'
    )
    products: Mapped[List['Product']] = relationship(
        'Product',
        secondary='attendee_products',
        back_populates='attendees',
        overlaps='attendee_products,attendee,product',
    )
    payment_products: Mapped[List['PaymentProduct']] = relationship(
        'PaymentProduct', back_populates='attendee'
    )

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )

    def get_product_quantity(self, product_id: int) -> int:
        for attendee_product in self.attendee_products:
            if attendee_product.product_id == product_id:
                return attendee_product.quantity
        return 0

    @property
    def group_id(self) -> Optional[int]:
        """Return the group_id from the related application."""
        return self.application.group_id if self.application else None


class AttendeeTicketApiKey(Base):
    """API keys to allow attendees retrieve their tickets via /attendees/tickets endpoint"""

    __tablename__ = 'attendee_ticket_api_keys'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    email: Mapped[str] = mapped_column(index=True)
    key: Mapped[str] = mapped_column(unique=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
