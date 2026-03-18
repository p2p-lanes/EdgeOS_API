from datetime import timedelta

import jwt
from fastapi import status

from app.core.config import settings
from app.core.utils import current_time


def test_invalid_token(client):
    response = client.get(
        '/applications/', headers={'Authorization': 'Bearer invalid_token'}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_expired_token(client):
    expired_token = jwt.encode(
        {
            'citizen_id': 1,
            'email': 'test@example.com',
            'exp': current_time() - timedelta(minutes=1),
        },
        settings.SECRET_KEY,
        algorithm='HS256',
    )

    response = client.get(
        '/applications/', headers={'Authorization': f'Bearer {expired_token}'}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()['detail'] == 'Token has expired'
