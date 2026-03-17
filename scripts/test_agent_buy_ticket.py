# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "httpx>=0.28",
#   "eth-account>=0.13",
#   "web3>=7.0",
#   "python-dotenv>=1.0",
# ]
# ///
"""
End-to-end test script for the x402 agent buy-ticket flow.

Usage:
    uv run scripts/test_agent_buy_ticket.py

Reads PRIVATE_KEY and X402_PAY_TO from .env file.

Optional env vars:
    API_URL      - default: http://localhost:8000
    EMAIL        - default: francisco@muvinai.com
    CHAIN_ID     - default: 8453 (Base Mainnet)
    USDC_ADDRESS - default: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
"""

import base64
import json
import os
import pathlib
import sys
import time

from dotenv import load_dotenv
import httpx
from eth_account import Account
from web3 import Web3

load_dotenv()

TOKEN_FILE = pathlib.Path(__file__).parent / '.jwt_token'

# ── Config ──────────────────────────────────────────────────────────────────

# API_URL = os.getenv('API_URL', 'https://portaldev.simplefi.tech')
API_URL = os.getenv('API_URL', 'http://localhost:8000')
EMAIL = os.getenv('EMAIL', 'francisco@muvinai.com')
PRIVATE_KEY = os.getenv('PRIVATE_KEY', '')
CHAIN_ID = int(os.getenv('CHAIN_ID', '8453'))
USDC_ADDRESS = os.getenv('USDC_ADDRESS', '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913')

if not PRIVATE_KEY:
    print('ERROR: Set PRIVATE_KEY env var (hex, with or without 0x prefix)')
    sys.exit(1)

account = Account.from_key(PRIVATE_KEY)
WALLET = account.address
print(f'Wallet: {WALLET}')
print(f'API:    {API_URL}')
print(f'Email:  {EMAIL}')
print()

client = httpx.Client(base_url=API_URL, timeout=30)


# ── Helpers ─────────────────────────────────────────────────────────────────


def encode_b64(data: dict) -> str:
    return base64.b64encode(json.dumps(data).encode()).decode()


def decode_b64(s: str) -> dict:
    return json.loads(base64.b64decode(s))


def sign_eip3009_transfer(pay_to: str, amount: str, timeout_seconds: int) -> dict:
    """Sign an EIP-3009 TransferWithAuthorization for USDC."""
    now = int(time.time())
    valid_after = str(now - 600)  # 10 min buffer in the past
    valid_before = str(now + timeout_seconds)
    nonce = '0x' + os.urandom(32).hex()

    domain = {
        'name': 'USD Coin',
        'version': '2',
        'chainId': CHAIN_ID,
        'verifyingContract': Web3.to_checksum_address(USDC_ADDRESS),
    }

    types = {
        'TransferWithAuthorization': [
            {'name': 'from', 'type': 'address'},
            {'name': 'to', 'type': 'address'},
            {'name': 'value', 'type': 'uint256'},
            {'name': 'validAfter', 'type': 'uint256'},
            {'name': 'validBefore', 'type': 'uint256'},
            {'name': 'nonce', 'type': 'bytes32'},
        ],
    }

    message = {
        'from': Web3.to_checksum_address(WALLET),
        'to': Web3.to_checksum_address(pay_to),
        'value': int(amount),
        'validAfter': int(valid_after),
        'validBefore': int(valid_before),
        'nonce': bytes.fromhex(nonce[2:]),
    }

    signed = account.sign_typed_data(
        domain_data=domain,
        message_types=types,
        message_data=message,
    )

    authorization = {
        'from': WALLET,
        'to': Web3.to_checksum_address(pay_to),
        'value': amount,
        'validAfter': valid_after,
        'validBefore': valid_before,
        'nonce': nonce,
    }

    return {
        'signature': '0x' + signed.signature.hex(),
        'authorization': authorization,
    }


# ── Step 1: Authenticate (cached) ──────────────────────────────────────────


def _get_token_from_file() -> str | None:
    """Load cached JWT and verify it's still valid."""
    if not TOKEN_FILE.exists():
        return None
    token = TOKEN_FILE.read_text().strip()
    if not token:
        return None
    # Quick check: does the API accept it?
    r = client.get('/applications', headers={'Authorization': f'Bearer {token}'})
    if r.status_code == 200:
        return token
    return None


def _authenticate() -> str:
    """OTP flow, returns JWT token."""
    print('=== Step 1: Request OTP ===')
    r = client.post(
        '/citizens/authenticate',
        json={'email': EMAIL, 'use_code': True},
    )
    print(f'Status: {r.status_code}')
    if r.status_code != 200:
        print(f'Error: {r.text}')
        sys.exit(1)
    print(r.json())

    code = input('\nEnter OTP code from email: ').strip()

    print('\n=== Step 2: Login ===')
    r = client.post(f'/citizens/login?email={EMAIL}&code={code}')
    print(f'Status: {r.status_code}')
    if r.status_code != 200:
        print(f'Error: {r.text}')
        sys.exit(1)

    return r.json()['access_token']


jwt_token = _get_token_from_file()
if jwt_token:
    print('=== Step 1: Using cached JWT token ===')
else:
    jwt_token = _authenticate()
    TOKEN_FILE.write_text(jwt_token)
    print('JWT saved to', TOKEN_FILE)

auth_headers = {'Authorization': f'Bearer {jwt_token}'}


# ── Step 3: Discover application & products ────────────────────────────────

print('\n=== Step 3: Discover application & products ===')

r = client.get('/applications', headers=auth_headers)
applications = r.json()
PREFERRED_POPUP_ID = int(os.getenv('POPUP_CITY_ID', '7'))
accepted = [a for a in applications if a.get('status', '').lower() == 'accepted']

if not accepted:
    print('No accepted applications found. Available:')
    for a in applications:
        print(f'  id={a["id"]} status={a.get("status")} popup={a.get("popup_city_id")}')
    sys.exit(1)

# Prefer the configured popup city
app = next(
    (a for a in accepted if a.get('popup_city_id') == PREFERRED_POPUP_ID), accepted[0]
)
app_id = app['id']
popup_city_id = app['popup_city_id']
print(f'Using application id={app_id}, popup_city_id={popup_city_id}')

# Get attendees from application detail
r = client.get(f'/applications/{app_id}', headers=auth_headers)
app_detail = r.json()
attendees = app_detail.get('attendees', [])
if not attendees:
    print('No attendees found for this application')
    sys.exit(1)

attendee_id = attendees[0]['id']
print(f'Using attendee id={attendee_id} ({attendees[0].get("name")})')

# Get products
r = client.get(
    '/products', headers=auth_headers, params={'popup_city_id': popup_city_id}
)
products = r.json()
active_products = [p for p in products if p.get('is_active')]

if not active_products:
    print('No active products found for this popup city')
    sys.exit(1)

print('Available products:')
for p in active_products:
    print(f'  id={p["id"]} name={p["name"]} price=${p.get("price", "?")}')

# Pick cheapest product by default, or use PRODUCT_ID env var
target_product_id = os.getenv('PRODUCT_ID')
if target_product_id:
    product = next(
        (p for p in active_products if str(p['id']) == target_product_id), None
    )
    if not product:
        print(f'Product id={target_product_id} not found')
        sys.exit(1)
else:
    product = min(active_products, key=lambda p: p.get('price', float('inf')))

product_id = product['id']
product_price = product.get('price', 0)
print(f'\nUsing product id={product_id} ({product["name"]}) @ ${product_price}')


# ── Step 4: Stage 1 — Request without payment → 402 ───────────────────────

print('\n=== Step 4: POST /agent/buy-ticket (no payment) → expect 402 ===')

buy_body = {
    'application_id': app_id,
    'products': [
        {
            'product_id': product_id,
            'attendee_id': attendee_id,
            'quantity': 1,
        }
    ],
}

r = client.post('/agent/buy-ticket', json=buy_body, headers=auth_headers)
print(f'Status: {r.status_code}')

if r.status_code != 402:
    print(f'Expected 402, got {r.status_code}')
    print(r.text)
    sys.exit(1)

# Parse PAYMENT-REQUIRED header
payment_required_header = r.headers.get('PAYMENT-REQUIRED', '')
if not payment_required_header:
    print('ERROR: No PAYMENT-REQUIRED header in 402 response')
    sys.exit(1)

payment_required = decode_b64(payment_required_header)
print(f'x402 Version: {payment_required.get("x402Version")}')
print(f'Accepts: {len(payment_required.get("accepts", []))} option(s)')

requirements = payment_required['accepts'][0]
amount = requirements['amount']
pay_to = requirements['payTo']
timeout = requirements.get('maxTimeoutSeconds', 60)

print(f'Amount: {amount} USDC atomic ({int(amount) / 1_000_000:.2f} USD)')
print(f'Pay to: {pay_to}')
print(f'Network: {requirements.get("network")}')

if payment_required.get('extensions', {}).get('agentkit'):
    agentkit_ext = payment_required['extensions']['agentkit']
    info = agentkit_ext.get('info', {})
    print(
        f'AgentKit challenge: domain={info.get("domain")}, nonce={info.get("nonce", "")[:20]}...'
    )

print('\n--- Stage 1 PASSED: 402 response is correct ---')

if not pay_to:
    print(
        '\nWARNING: X402_PAY_TO is not configured on the server. Set it in .env to proceed with payment.'
    )
    sys.exit(1)


# ── Step 5: Stage 2 — Sign payment and submit ─────────────────────────────

print('\n=== Step 5: Sign EIP-3009 payment & submit ===')

# Check USDC balance
w3 = Web3(Web3.HTTPProvider(os.getenv('RPC_URL', 'https://mainnet.base.org')))
usdc_abi = [
    {
        'inputs': [{'name': 'account', 'type': 'address'}],
        'name': 'balanceOf',
        'outputs': [{'name': '', 'type': 'uint256'}],
        'stateMutability': 'view',
        'type': 'function',
    }
]
usdc = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=usdc_abi)
balance = usdc.functions.balanceOf(Web3.to_checksum_address(WALLET)).call()
print(f'USDC balance: {balance / 1_000_000:.2f} USDC')

if balance < int(amount):
    print(
        f'ERROR: Insufficient USDC balance. Need {int(amount) / 1_000_000:.2f}, have {balance / 1_000_000:.2f}'
    )
    sys.exit(1)

# Sign the transfer authorization
payload_data = sign_eip3009_transfer(pay_to, amount, timeout)
print(f'Signed authorization from {WALLET}')

# Build the full x402 payment payload
payment_payload = {
    'x402Version': 2,
    'resource': {
        'url': f'{API_URL}/agent/buy-ticket',
        'description': requirements.get('description', ''),
        'mimeType': 'application/json',
    },
    'accepted': requirements,
    'payload': payload_data,
}

payment_signature = encode_b64(payment_payload)
print(f'Payment signature: {payment_signature[:60]}...')

# Submit with payment
r = client.post(
    '/agent/buy-ticket',
    json=buy_body,
    headers={
        **auth_headers,
        'PAYMENT-SIGNATURE': payment_signature,
    },
)

print(f'\nStatus: {r.status_code}')

if r.status_code == 200:
    data = r.json()
    print('\n--- Stage 2 PASSED: Payment successful! ---')
    print(f'Payment ID: {data.get("id")}')
    print(f'Status: {data.get("status")}')
    print(f'Amount: ${data.get("amount")}')
    print(f'Currency: {data.get("currency")}')
    print(f'Source: {data.get("source")}')
    print(f'External ID (tx): {data.get("external_id")}')
    print(f'Payer wallet: {data.get("payer_wallet")}')
    if data.get('products_snapshot'):
        print('Products:')
        for ps in data['products_snapshot']:
            print(f'  - {ps["product_name"]} @ ${ps["product_price"]}')

    # Check PAYMENT-RESPONSE header
    pr_header = r.headers.get('PAYMENT-RESPONSE', '')
    if pr_header:
        pr = decode_b64(pr_header)
        print(
            f'\nPAYMENT-RESPONSE: tx={pr.get("transaction")}, network={pr.get("network")}'
        )
else:
    print(f'Error: {r.text}')
    if r.status_code == 402:
        print('Payment verification/amount issue — check USDC balance and approval')
    elif r.status_code == 500:
        print('Settlement failed — check server logs')

client.close()
