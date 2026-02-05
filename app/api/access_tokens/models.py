from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import current_time


class AccessToken(Base):
    """Model to store access tokens for various external services"""

    __tablename__ = 'access_tokens'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    value: Mapped[str]
    expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
