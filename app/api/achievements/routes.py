from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.achievements import schemas

from app.api.achievements.crud import achievement as achievement_crud
from app.core.database import get_db
from app.core.security import TokenData, get_current_user

router = APIRouter()


@router.post(
    '', response_model=schemas.Achievement, status_code=status.HTTP_201_CREATED
)
def create_achievement(
    achievement: schemas.AchievementCreate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if achievement.achievement_type == 'badge':
        return achievement_crud.create_badge(db=db, obj=achievement, user=current_user)

    if current_user.citizen_id == achievement.receiver_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Sender and receiver cannot be the same',
        )

    return achievement_crud.create(db=db, obj=achievement, user=current_user)


@router.get('', response_model=schemas.AchievementResponse)
def get_achievements(
    current_user: TokenData = Depends(get_current_user),
    filters: schemas.AchievementFilter = Depends(),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    sort_by: str = Query(default='sent_at', description='Field to sort by'),
    sort_order: str = Query(default='desc', pattern='^(asc|desc)$'),
    db: Session = Depends(get_db),
):
    """Get all achievements (filtered by user permissions)"""
    return achievement_crud.get_user_achievements(
        db=db,
        user=current_user,
        skip=skip,
        limit=limit,
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order,
    )
