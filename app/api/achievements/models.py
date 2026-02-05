from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.citizens.models import Citizen


class Achievement(Base):
    __tablename__ = 'achievements'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    sender_id: Mapped[int | None] = mapped_column(ForeignKey('humans.id'), index=True)
    receiver_id: Mapped[int] = mapped_column(ForeignKey('humans.id'), index=True)
    achievement_type: Mapped[str]
    badge_type: Mapped[str | None]
    sent_at: Mapped[datetime] = mapped_column(default=current_time)
    message: Mapped[str | None]

    # Relationships to Citizen model
    sender: Mapped['Citizen'] = relationship('Citizen', foreign_keys=[sender_id])
    receiver: Mapped['Citizen'] = relationship('Citizen', foreign_keys=[receiver_id])
