from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import current_time


class CheckIn(Base):
    __tablename__ = 'check_ins'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    code: Mapped[str]
    attendee_id: Mapped[int] = mapped_column(ForeignKey('attendees.id'), unique=True)
    arrival_date: Mapped[datetime | None]
    departure_date: Mapped[datetime | None]
    virtual_check_in: Mapped[bool]
    virtual_check_in_timestamp: Mapped[datetime | None]
    qr_check_in: Mapped[bool]
    qr_scan_timestamp: Mapped[datetime | None]

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
