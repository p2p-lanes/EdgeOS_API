from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.citizens.models import Citizen


class AccountClusterMember(Base):
    """Represents membership of a citizen in an account cluster."""

    __tablename__ = 'account_cluster_members'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(index=True)
    citizen_id: Mapped[int] = mapped_column(ForeignKey('humans.id'), unique=True)
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)

    # Relationships
    citizen: Mapped['Citizen'] = relationship('Citizen')


class ClusterJoinRequest(Base):
    """Represents a pending request to join accounts into a cluster."""

    __tablename__ = 'cluster_join_requests'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    initiator_citizen_id: Mapped[int] = mapped_column(
        ForeignKey('humans.id'), index=True
    )
    target_citizen_id: Mapped[int] = mapped_column(ForeignKey('humans.id'), index=True)
    verification_code: Mapped[str] = mapped_column(unique=True, index=True)
    code_expiration: Mapped[datetime]
    # pending, verified, expired
    status: Mapped[str] = mapped_column(default='pending')
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)

    # Relationships
    initiator: Mapped['Citizen'] = relationship(
        'Citizen', foreign_keys=[initiator_citizen_id]
    )
    target: Mapped['Citizen'] = relationship(
        'Citizen', foreign_keys=[target_citizen_id]
    )
