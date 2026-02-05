from datetime import datetime

from sqlalchemy import ForeignKey, event
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, SessionLocal
from app.core.utils import current_time


class EmailLog(Base):
    __tablename__ = 'email_logs'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    receiver_email: Mapped[str] = mapped_column(index=True)
    event: Mapped[str]
    template: Mapped[str]
    params: Mapped[str | None]  # JSON string of parameters
    status: Mapped[str | None]  # success, failed, scheduled, canceled
    send_at: Mapped[datetime | None]
    error_message: Mapped[str | None]
    entity_type: Mapped[str | None]
    entity_id: Mapped[int | None]

    citizen_id: Mapped[int | None] = mapped_column(ForeignKey('humans.id'), index=True)
    popup_city_id: Mapped[int | None] = mapped_column(ForeignKey('popups.id'))

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]


@event.listens_for(EmailLog, 'before_insert')
def set_citizen_id(mapper, connection, target):
    if target.citizen_id or not target.receiver_email:
        return

    session = SessionLocal.object_session(target)
    if not session:
        return

    from app.api.citizens.models import Citizen

    citizen = (
        session.query(Citizen)
        .filter(Citizen.primary_email == target.receiver_email)
        .first()
    )

    if citizen:
        target.citizen_id = citizen.id
