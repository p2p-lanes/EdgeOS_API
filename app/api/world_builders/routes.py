from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.world_builders import schemas
from app.api.world_builders.crud import world_builder as world_builder_crud
from app.core.config import settings
from app.core.database import get_db

router = APIRouter()


@router.post('', response_model=schemas.WorldBuilder)
def create_world_builder(
    world_builder: schemas.WorldBuilderCreate,
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
):
    if x_api_key != settings.WORLD_BUILDERS_API_KEY:
        raise HTTPException(status_code=401, detail='Unauthorized')
    return world_builder_crud.create(db=db, obj=world_builder)


@router.get('/score', response_model=schemas.WorldBuilderScore)
def get_world_builder_score(
    address: str,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.WORLD_BUILDERS_API_KEY:
        raise HTTPException(status_code=401, detail='Unauthorized')
    return world_builder_crud.get_score(address=address)
