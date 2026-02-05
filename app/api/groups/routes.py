from typing import List, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.applications.schemas import Application, ApplicationWithAuth
from app.api.groups import schemas
from app.api.groups.crud import group as group_crud
from app.core.config import settings
from app.core.database import get_db
from app.core.logger import logger
from app.core.security import TokenData, get_current_user

router = APIRouter()


@router.get('/', response_model=list[schemas.Group])
def get_groups(
    current_user: TokenData = Depends(get_current_user),
    filters: schemas.GroupFilter = Depends(),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    sort_by: str = Query(default='name', description='Field to sort by'),
    sort_order: str = Query(default='asc', pattern='^(asc|desc)$'),
    db: Session = Depends(get_db),
):
    return group_crud.find(
        db=db,
        skip=skip,
        limit=limit,
        filters=filters,
        user=current_user,
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get('/{group_id}', response_model=schemas.GroupWithMembers)
def get_group(
    group_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return group_crud.get_with_members(db=db, id=group_id, user=current_user)


@router.get('/aux/{group_slug}', response_model=schemas.Group)
def get_group_aux(
    group_slug: str,
    api_key: str = Header(None, alias='api-key'),
    db: Session = Depends(get_db),
):
    if api_key != settings.GROUPS_API_KEY:
        raise HTTPException(status_code=401, detail='Unauthorized')
    return group_crud.get_by_slug(db=db, slug=group_slug)


@router.post('/{group_id}/new_member', response_model=ApplicationWithAuth)
def new_member(
    group_id: Union[int, str],
    member: schemas.GroupMember,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info('Adding new member to group %s: %s', group_id, member)
    application = group_crud.add_member(
        db=db,
        group_id=group_id,
        member=member,
        user=current_user,
        update_existing=True,
    )
    return ApplicationWithAuth(
        **Application.model_validate(application).model_dump(),
        authorization=application.citizen.get_authorization(),
    )


@router.post(
    '/{group_id}/members',
    response_model=schemas.MemberWithProducts,
    status_code=status.HTTP_201_CREATED,
)
def create_member(
    group_id: int,
    member: schemas.GroupMember,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    logger.info('Adding new member to group %s: %s', group_id, member)
    return group_crud.create_member(
        db=db,
        group_id=group_id,
        member=member,
        user=current_user,
    )


@router.post(
    '/{group_id}/members/batch',
    response_model=List[schemas.MemberBatchResult],
    status_code=status.HTTP_207_MULTI_STATUS,
)
def create_members_batch(
    group_id: int,
    batch: schemas.GroupMemberBatch,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create multiple members in a group at once, with partial success handling"""
    logger.info('Adding %d members to group %s', len(batch.members), group_id)

    return group_crud.create_members_batch(
        db=db,
        group_id=group_id,
        members=batch.members,
        user=current_user,
        update_existing=batch.update_existing,
    )


@router.put(
    '/{group_id}/members/{citizen_id}',
    response_model=schemas.MemberWithProducts,
    status_code=status.HTTP_200_OK,
)
def update_member(
    group_id: int,
    citizen_id: int,
    member: schemas.GroupMemberUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return group_crud.update_member(
        db=db,
        group_id=group_id,
        citizen_id=citizen_id,
        member=member,
        user=current_user,
    )


@router.delete(
    '/{group_id}/members/{citizen_id}',
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_member(
    group_id: int,
    citizen_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return group_crud.remove_member(
        db=db,
        group_id=group_id,
        citizen_id=citizen_id,
        user=current_user,
    )


@router.put('/{group_id}', response_model=schemas.Group, status_code=status.HTTP_200_OK)
def update_group(
    group_id: int,
    group: schemas.GroupUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return group_crud.update(
        db=db,
        id=group_id,
        obj=group,
        user=current_user,
    )
