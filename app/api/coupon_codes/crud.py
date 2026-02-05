from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.base_crud import CRUDBase
from app.api.coupon_codes import models, schemas
from app.core.security import SYSTEM_TOKEN
from app.core.utils import current_time


class CRUDCouponCode(
    CRUDBase[models.CouponCode, schemas.CouponCodeCreate, schemas.CouponCode]
):
    def get_by_code(self, db: Session, code: str, popup_city_id: int):
        coupon_code = (
            db.query(models.CouponCode)
            .filter(
                models.CouponCode.code.ilike(code),
                models.CouponCode.popup_city_id == popup_city_id,
            )
            .first()
        )
        if not coupon_code:
            raise HTTPException(
                status_code=404,
                detail='Coupon code not found. Please, enter a valid coupon.',
            )
        if not coupon_code.is_active:
            raise HTTPException(status_code=404, detail='Coupon code is not active')

        if coupon_code.start_date and coupon_code.start_date > current_time():
            raise HTTPException(
                status_code=404, detail='Coupon code has not started yet'
            )

        if coupon_code.end_date and coupon_code.end_date < current_time():
            raise HTTPException(status_code=404, detail='Coupon code has expired')

        current_uses = coupon_code.current_uses or 0
        if coupon_code.max_uses and current_uses >= coupon_code.max_uses:
            raise HTTPException(
                status_code=404,
                detail='Coupon code has reached the maximum number of uses',
            )

        return coupon_code

    def use_coupon_code(self, db: Session, coupon_code_id: int):
        coupon_code = self.get(db, coupon_code_id, user=SYSTEM_TOKEN)
        current_uses = coupon_code.current_uses or 0
        coupon_code.current_uses = current_uses + 1
        db.commit()


coupon_code = CRUDCouponCode(models.CouponCode)
