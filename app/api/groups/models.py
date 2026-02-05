import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.api.popup_city.models import PopUpCity
from app.core.config import settings
from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.applications.models import Application
    from app.api.citizens.models import Citizen
    from app.api.products.models import Product


class GroupLeader(Base):
    __tablename__ = 'group_leaders'

    citizen_id: Mapped[int] = mapped_column(ForeignKey('humans.id'), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.id'), primary_key=True)


class GroupMembers(Base):
    __tablename__ = 'group_members'

    citizen_id: Mapped[int] = mapped_column(ForeignKey('humans.id'), primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey('groups.id'), primary_key=True)


class GroupProducts(Base):
    __tablename__ = 'group_products'

    group_id: Mapped[int] = mapped_column(ForeignKey('groups.id'), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey('products.id'), primary_key=True)


class Group(Base):
    __tablename__ = 'groups'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None]
    discount_percentage: Mapped[float]
    popup_city_id: Mapped[int] = mapped_column(ForeignKey('popups.id'), index=True)
    max_members: Mapped[int | None]
    is_ambassador_group: Mapped[bool] = mapped_column(default=False)
    ambassador_id: Mapped[int | None] = mapped_column(ForeignKey('humans.id'))
    ambassador_email: Mapped[str | None]
    welcome_message: Mapped[str | None]

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]

    applications: Mapped[List['Application']] = relationship(
        'Application', back_populates='group'
    )
    leaders: Mapped[List['Citizen']] = relationship(
        'Citizen', secondary='group_leaders', backref='led_groups'
    )
    members: Mapped[List['Citizen']] = relationship(
        'Citizen', secondary='group_members', back_populates='groups_as_member'
    )
    ambassador: Mapped['Citizen'] = relationship(
        'Citizen', foreign_keys=[ambassador_id], back_populates='groups_as_ambassador'
    )
    products: Mapped[List['Product']] = relationship(
        'Product', secondary='group_products', backref='groups'
    )
    popup_city: Mapped['PopUpCity'] = relationship('PopUpCity', lazy='joined')

    @property
    def popup_name(self) -> str:
        return self.popup_city.name

    @property
    def express_checkout_background(self) -> Optional[str]:
        return self.popup_city.express_checkout_background

    @property
    def web_url(self) -> Optional[str]:
        return self.popup_city.web_url

    def is_leader(self, citizen_id: int) -> bool:
        return any(leader.id == citizen_id for leader in self.leaders)

    def express_checkout_url(self) -> Optional[str]:
        return urllib.parse.urljoin(
            settings.FRONTEND_URL,
            f'/{self.popup_city.slug}/invite/{self.slug}',
        )
