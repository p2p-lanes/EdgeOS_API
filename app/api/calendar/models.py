from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import current_time


class CalendarSubscription(Base):
    """Per-citizen revocable token used to authenticate iCal feed requests.

    Calendar apps poll the `.ics` feed unauthenticated (no cookies / OAuth), so the
    bearer secret lives in the URL. There is a single active token per citizen; it can
    be regenerated (rotates the token, old URL stops working) or revoked (row deleted).
    """

    __tablename__ = 'calendar_subscriptions'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    citizen_id: Mapped[int] = mapped_column(
        ForeignKey('humans.id'), unique=True, index=True
    )
    token: Mapped[str] = mapped_column(unique=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
