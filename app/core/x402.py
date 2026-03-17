import base64
import json

import httpx

from app.core.config import settings
from app.core.logger import logger


def usd_to_usdc_atomic(usd: float) -> str:
    """Convert USD amount to USDC atomic units (6 decimals). e.g. 500.00 -> '500000000'"""
    return str(int(round(usd * 1_000_000)))


def build_payment_requirements(price_usd: float) -> dict:
    """Build requirements used both for the 402 response and facilitator calls."""
    amount = usd_to_usdc_atomic(price_usd)
    return {
        'scheme': 'exact',
        'network': settings.X402_NETWORK,
        'amount': amount,
        'asset': settings.X402_USDC_ADDRESS,
        'payTo': settings.X402_PAY_TO,
        'maxTimeoutSeconds': settings.X402_MAX_TIMEOUT,
        'extra': {'name': 'USD Coin', 'version': '2', 'assetTransferMethod': 'eip3009'},
    }


def build_payment_required_response(
    price_usd: float,
    resource_url: str,
    description: str,
    agentkit_ext: dict | None = None,
) -> dict:
    requirements = build_payment_requirements(price_usd)
    body = {
        'x402Version': 2,
        'resource': {
            'url': resource_url,
            'description': description,
            'mimeType': 'application/json',
        },
        'accepts': [requirements],
        'error': 'Payment Required',
    }
    if agentkit_ext:
        body['extensions'] = {'agentkit': agentkit_ext}
    return body


def encode_header(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode()).decode()


def decode_header(header: str) -> dict:
    return json.loads(base64.b64decode(header))


def verify_payment(payment_payload: dict, requirements: dict) -> dict:
    """POST to facilitator /verify endpoint."""
    url = f'{settings.X402_FACILITATOR_URL}/verify'
    logger.info('Verifying x402 payment at %s', url)
    body = {
        'x402Version': 2,
        'paymentPayload': payment_payload,
        'paymentRequirements': requirements,
    }
    logger.debug('Verify request body: %s', json.dumps(body)[:500])
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.post(url, json=body)
        if response.status_code >= 400:
            logger.error(
                'Facilitator /verify returned %s: %s',
                response.status_code,
                response.text[:500],
            )
        response.raise_for_status()
        return response.json()


def settle_payment(payment_payload: dict, requirements: dict) -> dict:
    """POST to facilitator /settle endpoint."""
    url = f'{settings.X402_FACILITATOR_URL}/settle'
    logger.info('Settling x402 payment at %s', url)
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.post(
            url,
            json={
                'x402Version': 2,
                'paymentPayload': payment_payload,
                'paymentRequirements': requirements,
            },
        )
        if response.status_code >= 400:
            logger.error(
                'Facilitator /settle returned %s: %s',
                response.status_code,
                response.text[:500],
            )
        response.raise_for_status()
        return response.json()
