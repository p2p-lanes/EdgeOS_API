from datetime import timedelta
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.core.config import settings
from app.core.logger import logger
from app.core.utils import current_time


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    citizen_id: int
    email: str


# Constants
ALGORITHM = 'HS256'
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# System token used for internal service operations
# citizen_id=0 represents a system-level operation rather than a real user
SYSTEM_TOKEN = TokenData(citizen_id=0, email='')

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='auth/token')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        to_encode.update({'exp': current_time() + expires_delta})

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme)) -> TokenData:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail='Could not validate credentials',
        headers={'WWW-Authenticate': 'Bearer'},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.error('Token has expired')
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail='Token has expired',
            headers={'WWW-Authenticate': 'Bearer'},
        )
    except jwt.InvalidTokenError as e:
        logger.error('Error decoding token: %s', str(e))
        raise credentials_exception

    citizen_id: int = payload.get('citizen_id')
    email: str = payload.get('email')
    if citizen_id is None or email is None:
        logger.error('Invalid token payload: %s', payload)
        raise credentials_exception

    return TokenData(citizen_id=citizen_id, email=email)
