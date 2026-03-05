import os
from typing import Optional
from urllib.parse import unquote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import FileResponse
from pydantic import validate_email
from pydantic_core import PydanticCustomError
from sqlalchemy.orm import Session

from app.api.authorized_third_party_apps.crud import (
    authorized_third_party_app as authorized_third_party_app_crud,
)
from app.api.citizens import schemas
from app.api.citizens.crud import citizen as citizen_crud
from app.core.database import get_db
from app.core.config import settings
from app.core.logger import logger
from app.core.security import TokenData, get_current_user
from app.core.world import verify_safe_signature

router = APIRouter()


@router.post('/signup', response_model=schemas.Citizen)
def signup(
    citizen: schemas.CitizenCreate,
    db: Session = Depends(get_db),
):
    logger.info('Signing up citizen: %s', citizen)
    return citizen_crud.signup(db=db, obj=citizen)


@router.post('/authenticate')
def authenticate(
    data: schemas.Authenticate,
    db: Session = Depends(get_db),
):
    logger.info('Authenticating citizen: %s', data)

    # Check if world_address is provided and exists in database
    if not data.email:
        if not data.signature:
            raise HTTPException(status_code=400, detail='Signature must be provided')

        if data.source == 'app' and data.world_address:
            if not verify_safe_signature(data.world_address, data.signature):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail='Invalid signature from app',
                )
            else:
                existing_citizen_by_world_address = citizen_crud.get_by_world_address(
                    db, data.world_address
                )
                if existing_citizen_by_world_address:
                    if not existing_citizen_by_world_address.primary_email:
                        raise HTTPException(
                            status_code=400,
                            detail='Citizen has no email configured',
                        )
                    citizen = citizen_crud.login(
                        db=db,
                        email=existing_citizen_by_world_address.primary_email,
                        world_address=data.world_address,
                        spice=existing_citizen_by_world_address.spice,
                    )
                    return citizen.get_authorization()
                else:
                    # World address provided but not found in database
                    raise HTTPException(
                        status_code=404,
                        detail='Citizen with this world address not found',
                    )

    return citizen_crud.authenticate(
        db=db,
        data=data,
    )


@router.post('/authenticate-third-party')
def authenticate_third_party(
    data: schemas.AuthenticateThirdParty,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    logger.info('Authenticating third-party citizen: %s', data)
    authorized_third_party_app = authorized_third_party_app_crud.get_by_api_key(
        db=db, api_key=x_api_key
    )
    if not authorized_third_party_app:
        raise HTTPException(status_code=401, detail='Invalid API key')
    return citizen_crud.authenticate_third_party(
        db=db,
        email=data.email,
        app_name=authorized_third_party_app.name,
    )


@router.post('/authenticate-edgeclaw')
def authenticate_edgeclaw(
    data: schemas.AuthenticateThirdParty,
    db: Session = Depends(get_db),
):
    logger.info('Authenticating EdgeClaw citizen: %s', data)
    authorized_third_party_app = authorized_third_party_app_crud.get_by_api_key(
        db=db, api_key=settings.EDGECLAW_API_KEY
    )
    if not authorized_third_party_app:
        raise HTTPException(status_code=404, detail='EdgeClaw app not found')
    return citizen_crud.authenticate_third_party(
        db=db,
        email=data.email,
        app_name=authorized_third_party_app.name,
    )


@router.post('/login')
def login(
    email: str,
    spice: Optional[str] = None,
    code: Optional[int] = None,
    world_address: Optional[str] = None,
    verified_upon_login: Optional[str] = None,
    db: Session = Depends(get_db),
):
    try:
        _, email = validate_email(unquote(email))
    except PydanticCustomError:
        raise HTTPException(status_code=400, detail='Invalid email format')

    logger.info('Logging in citizen: %s', email)
    if not spice and not code:
        logger.error('Either spice or code must be provided')
        raise HTTPException(
            status_code=400, detail='Either spice or code must be provided'
        )

    citizen = citizen_crud.login(
        db=db,
        email=email,
        spice=spice,
        code=code,
        world_address=world_address,
        verified_upon_login=verified_upon_login,
    )
    return citizen.get_authorization()


@router.post('/app-logout')
def logout(
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return citizen_crud.logout(db=db, user=current_user)


# Get all citizens
@router.get('', response_model=list[schemas.Citizen])
def get_citizens(
    current_user: TokenData = Depends(get_current_user),
    filters: schemas.CitizenFilter = Depends(),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return citizen_crud.find(
        db=db,
        skip=skip,
        limit=limit,
        filters=filters,
        user=current_user,
    )


@router.get('/my-poaps', response_model=schemas.CitizenPoaps)
def get_my_poaps(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    return citizen_crud.get_poaps_from_citizen(db=db, user=current_user)


@router.get('/profile', response_model=schemas.CitizenProfile)
def get_profile(
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    _, profile = citizen_crud.get_profile(db=db, user=current_user)
    return profile


@router.get('/edge-mapped')
def get_edge_mapped(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    image_path = citizen_crud.get_edge_mapped(db=db, user=current_user)
    background_tasks.add_task(os.remove, image_path)

    return FileResponse(
        image_path,
        media_type='image/png',
        headers={'Content-Disposition': 'inline; filename="edge-mapped.png"'},
    )


# Get citizen by ID
@router.get('/{citizen_id}', response_model=schemas.Citizen)
def get_citizen(
    citizen_id: int,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return citizen_crud.get(db=db, id=citizen_id, user=current_user)


@router.put('/me', response_model=schemas.Citizen)
def update_me(
    citizen: schemas.CitizenUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return citizen_crud.update(
        db=db,
        id=current_user.citizen_id,
        obj=citizen,
        user=current_user,
    )


@router.get('/email/{email}', response_model=schemas.Citizen)
def get_citizen_by_email(
    email: str,
    db: Session = Depends(get_db),
):
    try:
        _, email = validate_email(unquote(email))
    except PydanticCustomError:
        raise HTTPException(status_code=400, detail='Invalid email')

    citizen = citizen_crud.get_by_email(db=db, email=email)
    if not citizen:
        raise HTTPException(status_code=404, detail='Citizen not found')
    return citizen
