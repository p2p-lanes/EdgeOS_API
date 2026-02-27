from datetime import datetime
from typing import List

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time


class EmailTemplate(Base):
    __tablename__ = 'popup_email_templates'

    id: Mapped[int] = mapped_column(primary_key=True)
    popup_city_id: Mapped[int] = mapped_column(ForeignKey('popups.id'))
    event: Mapped[str]
    template: Mapped[str]
    frequency: Mapped[str | None]
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )

    popup_city: Mapped['PopUpCity'] = relationship(
        'PopUpCity', back_populates='templates'
    )


class PopUpCity(Base):
    __tablename__ = 'popups'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    name: Mapped[str] = mapped_column(index=True)
    slug: Mapped[str] = mapped_column(index=True, unique=True)
    prefix: Mapped[str] = mapped_column(unique=True)
    tagline: Mapped[str | None]
    location: Mapped[str | None]
    passes_description: Mapped[str | None]
    image_url: Mapped[str | None]
    express_checkout_background: Mapped[str | None]
    web_url: Mapped[str | None]
    email_image: Mapped[str | None]
    contact_email: Mapped[str | None]
    ticketing_banner_description: Mapped[str | None]
    blog_url: Mapped[str | None]
    twitter_url: Mapped[str | None]
    start_date: Mapped[datetime | None]
    end_date: Mapped[datetime | None]
    installments_deadline: Mapped[datetime | None]
    allows_spouse: Mapped[bool | None] = mapped_column(default=False)
    allows_children: Mapped[bool | None] = mapped_column(default=False)
    allows_coupons: Mapped[bool | None] = mapped_column(default=False)
    clickable_in_portal: Mapped[bool | None] = mapped_column(default=False)
    visible_in_portal: Mapped[bool | None] = mapped_column(default=False)
    requires_approval: Mapped[bool] = mapped_column(default=True)
    auto_approval_time: Mapped[int | None]  # in minutes
    portal_order: Mapped[float] = mapped_column(default=0)
    simplefi_api_key: Mapped[str | None]
    applications_imported: Mapped[bool] = mapped_column(default=False)
    ai_review_prompt: Mapped[str | None]

    templates: Mapped[List[EmailTemplate]] = relationship(
        'EmailTemplate', back_populates='popup_city'
    )

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]

    def get_email_template(self, event: str) -> str:
        for t in self.templates:
            if t.event == event:
                return t.template
        raise ValueError(
            f'No template found for event: {event} (popup_city: {self.id} {self.name})'
        )
