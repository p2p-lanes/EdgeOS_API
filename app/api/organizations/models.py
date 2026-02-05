from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.utils import current_time

if TYPE_CHECKING:
    from app.api.citizens.models import Citizen


class Organization(Base):
    __tablename__ = 'organizations'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)

    citizens: Mapped[List['Citizen']] = relationship(
        'Citizen',
        secondary='citizen_organizations',
        back_populates='organizations',
    )

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]
