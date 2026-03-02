from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.coupon_codes import schemas
from app.api.coupon_codes.crud import coupon_code as coupon_code_crud
from app.core.config import settings
from app.core.database import get_db
from app.core.logger import logger
from app.core.security import TokenData, get_current_user

router = APIRouter()


@router.get('', response_model=schemas.CouponCode)
def get_coupon_code(
    current_user: TokenData = Depends(get_current_user),
    code: str = Query(),
    popup_city_id: int = Query(),
    db: Session = Depends(get_db),
):
    return coupon_code_crud.get_by_code(
        db=db,
        code=code,
        popup_city_id=popup_city_id,
    )


@router.post('', response_model=schemas.CouponCode)
def create_coupon_code(
    coupon_code: schemas.CouponCodeCreate,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    logger.info('Creating coupon code: %s', coupon_code)
    if x_api_key != settings.COUPON_API_KEY:
        logger.error('Invalid API key')
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Invalid API key',
        )
    return coupon_code_crud.create(db=db, obj=coupon_code)
