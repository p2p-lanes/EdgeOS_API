from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import current_time


class AuthorizedThirdPartyApp(Base):
    __tablename__ = 'authorized_third_party_apps'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    name: Mapped[str]
    api_key: Mapped[str]
    active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
