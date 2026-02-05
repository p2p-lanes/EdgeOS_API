from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.security import Token, create_access_token
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.applications.models import Application
    from app.api.groups.models import Group
    from app.api.organizations.models import Organization

# Association table for citizen-organization many-to-many relationship
citizen_organizations = Table(
    'citizen_organizations',
    Base.metadata,
    Column('citizen_id', Integer, ForeignKey('humans.id'), primary_key=True),
    Column(
        'organization_id', Integer, ForeignKey('organizations.id'), primary_key=True
    ),
    Column('created_at', DateTime, default=current_time),
)


class Citizen(Base):
    __tablename__ = 'humans'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    primary_email: Mapped[str | None] = mapped_column(index=True)
    secondary_email: Mapped[str | None]
    first_name: Mapped[str | None]
    last_name: Mapped[str | None]
    x_user: Mapped[str | None]
    telegram: Mapped[str | None]
    organization: Mapped[str | None]
    role: Mapped[str | None]
    residence: Mapped[str | None]
    social_media: Mapped[str | None]
    age: Mapped[str | None]
    gender: Mapped[str | None]
    eth_address: Mapped[str | None]
    world_address: Mapped[str | None]
    verified_upon_login: Mapped[str | None]
    referral: Mapped[str | None]
    picture_url: Mapped[str | None]
    red_flag: Mapped[bool | None] = mapped_column(default=False)
    edge_mapped_sent: Mapped[bool | None] = mapped_column(default=False)

    email_validated: Mapped[bool | None] = mapped_column(default=False)
    spice: Mapped[str | None]
    code: Mapped[int | None]
    code_expiration: Mapped[datetime | None]
    third_party_app: Mapped[str | None]

    applications: Mapped[List['Application']] = relationship(
        'Application', back_populates='citizen'
    )
    groups_as_member: Mapped[List['Group']] = relationship(
        'Group', secondary='group_members', back_populates='members'
    )
    groups_as_ambassador: Mapped[List['Group']] = relationship(
        'Group', back_populates='ambassador', foreign_keys='Group.ambassador_id'
    )

    # Replace the single organization relationship with many-to-many
    organizations: Mapped[List['Organization']] = relationship(
        'Organization',
        secondary=citizen_organizations,
        back_populates='citizens',
    )

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]

    def get_application(self, popup_city_id: int) -> Optional['Application']:
        for application in self.applications:
            if application.popup_city_id == popup_city_id:
                return application
        return None

    def get_authorization(self) -> Token:
        data = {
            'citizen_id': self.id,
            'email': self.primary_email,
            'iat': int(current_time().timestamp()),
        }
        if self.third_party_app:
            data['third_party_app'] = self.third_party_app
        return Token(
            access_token=create_access_token(data=data),
            token_type='Bearer',
        )

    __table_args__ = (
        Index(
            'ix_humans_primary_email_unique',
            'primary_email',
            unique=True,
            postgresql_where=(primary_email.is_not(None)),
        ),
    )


@event.listens_for(Citizen, 'before_insert')
def clean_email(mapper, connection, target):
    if target.primary_email:
        target.primary_email = target.primary_email.lower().strip()
    if target.secondary_email:
        target.secondary_email = target.secondary_email.lower().strip()
