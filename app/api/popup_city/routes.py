from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.popup_city import schemas
from app.api.popup_city.crud import popup_city as popup_city_crud
from app.core.config import settings
from app.core.database import get_db
from app.core.security import TokenData, get_current_user

router = APIRouter()


@router.get('/', response_model=list[schemas.PopUpCity])
def get_popup_cities(
    current_user: TokenData = Depends(get_current_user),
    skip: int = 0,
    limit: int = 100,
    sort_by: str = Query(default='portal_order', description='Field to sort by'),
    sort_order: str = Query(default='asc', pattern='^(asc|desc)$'),
    db: Session = Depends(get_db),
):
    return popup_city_crud.find(
        db=db,
        skip=skip,
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get('/{popup_city_id}', response_model=schemas.PopUpCity)
def get_popup_city(
    popup_city_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_popup_city = popup_city_crud.get(db=db, id=popup_city_id, user=current_user)
    if db_popup_city is None:
        raise HTTPException(status_code=404, detail='Popup city not found')
    return db_popup_city


@router.post('/{popup_city_id}/send_reminder_emails')
def send_reminder_emails(
    popup_city_id: int,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    if x_api_key != settings.REMINDER_EMAILS_API_KEY:
        raise HTTPException(status_code=403, detail='Invalid API key')

    return popup_city_crud.send_reminder_emails(db=db, popup_city_id=popup_city_id)
