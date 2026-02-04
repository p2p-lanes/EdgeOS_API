from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.applications.models import Application
    from app.api.payments.models import PaymentProduct
    from app.api.products.models import Product


class AttendeeProduct(Base):
    __tablename__ = 'attendee_products'

    attendee_id = Column(Integer, ForeignKey('attendees.id'), primary_key=True)
    product_id = Column(Integer, ForeignKey('products.id'), primary_key=True)
    quantity = Column(Integer, nullable=False, default=1)
    insurance_applied = Column(Boolean, default=False)
    insurance_price = Column(Float, nullable=True)

    attendee: Mapped['Attendee'] = relationship(
        'Attendee', back_populates='attendee_products'
    )
    product: Mapped['Product'] = relationship(
        'Product', back_populates='attendee_products'
    )


class Attendee(Base):
    __tablename__ = 'attendees'

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
        unique=True,
        index=True,
    )
    application_id = Column(Integer, ForeignKey('applications.id'), nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    email = Column(String)
    gender = Column(String)
    poap_url = Column(String)
    check_in_code = Column(String, nullable=False)

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

    created_at = Column(DateTime, default=current_time)
    updated_at = Column(DateTime, default=current_time, onupdate=current_time)

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

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    email = Column(String, nullable=False, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=current_time)
