from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.utils import current_time


class CouponCode(Base):
    __tablename__ = 'coupon_codes'
    __table_args__ = (
        UniqueConstraint('code', 'popup_city_id', name='uix_code_popup_city'),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, index=True)
    code: Mapped[str | None] = mapped_column(index=True)
    popup_city_id: Mapped[int] = mapped_column(ForeignKey('popups.id'), index=True)
    _discount_value: Mapped[str | None] = mapped_column('discount_value', String)
    max_uses: Mapped[int | None]
    current_uses: Mapped[int | None] = mapped_column(default=0)
    start_date: Mapped[datetime | None]
    end_date: Mapped[datetime | None]
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime | None] = mapped_column(default=current_time)
    updated_at: Mapped[datetime | None] = mapped_column(
        default=current_time, onupdate=current_time
    )
    created_by: Mapped[str | None]
    updated_by: Mapped[str | None]

    @property
    def discount_value(self) -> Optional[float]:
        if not self._discount_value:
            return None
        return float(self._discount_value)

    @discount_value.setter
    def discount_value(self, value: Optional[float]) -> None:
        self._discount_value = str(value) if value is not None else None
