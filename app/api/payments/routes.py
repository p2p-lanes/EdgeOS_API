from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.payments import schemas
from app.api.payments.crud import payment as payment_crud
from app.core.database import get_db
from app.core.logger import logger
from app.core.security import TokenData, get_current_user

router = APIRouter()


@router.get('', response_model=list[schemas.Payment])
def get_payments(
    current_user: TokenData = Depends(get_current_user),
    filters: schemas.PaymentFilter = Depends(),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return payment_crud.find(
        db=db,
        skip=skip,
        limit=limit,
        filters=filters,
        user=current_user,
    )


@router.get('/{payment_id}', response_model=schemas.Payment)
def get_payment(
    payment_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return payment_crud.get(db=db, id=payment_id, user=current_user)


@router.post('', response_model=schemas.Payment)
def create_payment(
    payment: schemas.PaymentCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info('%s Creating payment: %s', current_user.email, payment)
    return payment_crud.create(db=db, obj=payment, user=current_user)


@router.post('/preview', response_model=schemas.PaymentPreview)
def preview_payment(
    payment: schemas.PaymentCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info('%s Previewing payment: %s', current_user.email, payment)
    return payment_crud.preview(db=db, obj=payment, user=current_user)
