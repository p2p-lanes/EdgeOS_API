import time
import urllib.parse
from typing import Optional

import requests

from app.core.config import settings
from app.core.logger import logger


def _create_payment_request(body: dict, simplefi_api_key: str):
    def post_request():
        return requests.post(
            f'{settings.SIMPLEFI_API_URL}/payment_requests',
            json=body,
            headers={'Authorization': f'Bearer {simplefi_api_key}'},
            timeout=20,
        )

    try:
        response = post_request()
        logger.info('Simplefi response status: %s', response.status_code)
        retry = response.status_code >= 400
    except requests.exceptions.RequestException as e:
        logger.error('Simplefi error: %s', e)
        retry = True

    if retry:
        logger.error('Simplefi error, retrying...')
        time.sleep(5)
        response = post_request()
        logger.info('Simplefi response status (retry): %s', response.status_code)

    response.raise_for_status()
    return response.json()


def _create_installments_plan(body: dict, simplefi_api_key: str):
    def post_request():
        return requests.post(
            f'{settings.SIMPLEFI_API_URL}/installment_plans',
            json=body,
            headers={'Authorization': f'Bearer {simplefi_api_key}'},
            timeout=20,
        )

    try:
        response = post_request()
        logger.info('Simplefi response status: %s', response.status_code)
        retry = response.status_code >= 400
    except requests.exceptions.RequestException as e:
        logger.error('Simplefi error: %s', e)
        retry = True

    if retry:
        logger.error('Simplefi error, retrying...')
        time.sleep(5)
        response = post_request()
        logger.info('Simplefi response status (retry): %s', response.status_code)

    response.raise_for_status()
    return response.json()


def create_payment(
    amount: float,
    *,
    simplefi_api_key: str,
    reference: Optional[dict] = None,
    max_installments: Optional[int] = None,
    name: Optional[str] = None,
) -> dict:
    logger.info('Creating payment for amount: %s', amount)
    notification_url = urllib.parse.urljoin(settings.BACKEND_URL, 'webhooks/simplefi')

    if max_installments is not None and max_installments > 1:
        body = {
            'name': name,
            'total_amount': amount,
            'currency': 'USD',
            'max_installments': max_installments,
            'user_email': reference['email'],
            'reference': reference if reference else {},
            'interval': 'week',
            'interval_count': 2,  # every 2 weeks
            'notification_url': notification_url,
        }
        return _create_installments_plan(body, simplefi_api_key)

    body = {
        'amount': amount,
        'currency': 'USD',
        'reference': reference if reference else {},
        'memo': 'Citizen Portal Payment',
        'notification_url': notification_url,
    }

    return _create_payment_request(body, simplefi_api_key)
