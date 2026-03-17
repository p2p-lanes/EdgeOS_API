import base64
import json
import os
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from app.core.config import settings
from app.core.logger import logger

# ABI for AgentBook.lookupHuman(address) -> uint256
AGENTBOOK_ABI = [
    {
        'inputs': [{'name': '', 'type': 'address'}],
        'name': 'lookupHuman',
        'outputs': [{'name': '', 'type': 'uint256'}],
        'stateMutability': 'view',
        'type': 'function',
    }
]

# ABI for ERC-1271 isValidSignature(bytes32, bytes) -> bytes4
ERC1271_ABI = [
    {
        'inputs': [
            {'name': 'hash', 'type': 'bytes32'},
            {'name': 'signature', 'type': 'bytes'},
        ],
        'name': 'isValidSignature',
        'outputs': [{'name': '', 'type': 'bytes4'}],
        'stateMutability': 'view',
        'type': 'function',
    }
]

# ERC-1271 magic value indicating valid signature
ERC1271_MAGIC_VALUE = bytes.fromhex('1626ba7e')

# Required fields in an AgentKit payload (per AgentKit spec AgentkitPayloadSchema)
REQUIRED_PAYLOAD_FIELDS = {
    'domain',
    'address',
    'uri',
    'version',
    'chainId',
    'type',
    'nonce',
    'issuedAt',
    'signature',
}

# JSON Schema describing the expected agentkit header payload
AGENTKIT_PAYLOAD_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'properties': {
        'domain': {'type': 'string'},
        'address': {'type': 'string'},
        'uri': {'type': 'string', 'format': 'uri'},
        'version': {'type': 'string'},
        'chainId': {'type': 'string'},
        'type': {'type': 'string'},
        'nonce': {'type': 'string'},
        'issuedAt': {'type': 'string', 'format': 'date-time'},
        'signature': {'type': 'string'},
        'resources': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': sorted(REQUIRED_PAYLOAD_FIELDS),
}

DEFAULT_MAX_AGE_SECONDS = 300  # 5 minutes


# ── Nonce replay protection ────────────────────────────────────────────────


class _NonceCache:
    """Thread-safe in-memory nonce cache with TTL-based expiry."""

    def __init__(self, ttl: int = DEFAULT_MAX_AGE_SECONDS):
        self._ttl = ttl
        self._nonces: dict[str, float] = {}
        self._lock = threading.Lock()

    def _evict(self) -> None:
        cutoff = time.time() - self._ttl
        self._nonces = {k: v for k, v in self._nonces.items() if v > cutoff}

    def check_and_record(self, nonce: str) -> bool:
        """Return True if nonce is fresh (not seen before). Records it."""
        with self._lock:
            self._evict()
            if nonce in self._nonces:
                return False
            self._nonces[nonce] = time.time()
            return True


_nonce_cache = _NonceCache()


# ── 402 challenge builder ──────────────────────────────────────────────────


def build_agentkit_challenge(domain: str, resource_uri: str) -> dict:
    """Build the agentkit extension for a 402 response per AgentKit spec."""
    nonce = os.urandom(16).hex()
    issued_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace('+00:00', 'Z')
    )
    network = settings.X402_NETWORK
    discount_pct = settings.AGENTKIT_DISCOUNT_PERCENT

    ext: dict = {
        'info': {
            'domain': domain,
            'uri': resource_uri,
            'version': '1',
            'nonce': nonce,
            'issuedAt': issued_at,
            'resources': [resource_uri],
        },
        'supportedChains': [
            {'chainId': network, 'type': 'eip191'},
            {'chainId': network, 'type': 'eip1271'},
        ],
        'schema': AGENTKIT_PAYLOAD_SCHEMA,
    }
    if discount_pct > 0:
        ext['mode'] = {'type': 'discount', 'percent': discount_pct}
    return ext


# ── Header parsing ─────────────────────────────────────────────────────────


def parse_agentkit_header(header: str) -> dict:
    """Base64-decode and validate an agentkit header payload."""
    payload = json.loads(base64.b64decode(header))
    missing = REQUIRED_PAYLOAD_FIELDS - set(payload.keys())
    if missing:
        raise ValueError(f'Missing required agentkit fields: {missing}')
    return payload


# ── Message validation ─────────────────────────────────────────────────────


def validate_agentkit_message(
    payload: dict, expected_domain: str, expected_uri: str
) -> bool:
    """Validate domain, URI host, temporal fields, and nonce per AgentKit spec."""
    # Domain check
    if payload.get('domain') != expected_domain:
        logger.warning(
            'AgentKit domain mismatch: %s != %s', payload.get('domain'), expected_domain
        )
        return False

    # URI host check (AgentKit compares netloc, not full URI)
    try:
        payload_host = urlparse(payload.get('uri', '')).netloc
        expected_host = urlparse(expected_uri).netloc
        if payload_host != expected_host:
            logger.warning(
                'AgentKit URI host mismatch: %s != %s', payload_host, expected_host
            )
            return False
    except Exception:
        logger.warning('AgentKit URI parsing failed')
        return False

    # issuedAt freshness check
    issued_at_str = payload.get('issuedAt', '')
    try:
        issued_at = datetime.fromisoformat(issued_at_str)
        if issued_at.tzinfo is None:
            issued_at = issued_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - issued_at).total_seconds()
        if age > DEFAULT_MAX_AGE_SECONDS:
            logger.warning('AgentKit message too old: %ds', age)
            return False
        if age < 0:
            logger.warning('AgentKit issuedAt is in the future')
            return False
    except (ValueError, TypeError):
        logger.warning('AgentKit invalid issuedAt: %s', issued_at_str)
        return False

    # expirationTime check (optional)
    expiration_str = payload.get('expirationTime')
    if expiration_str:
        try:
            expiration = datetime.fromisoformat(expiration_str)
            if expiration.tzinfo is None:
                expiration = expiration.replace(tzinfo=timezone.utc)
            if expiration < datetime.now(timezone.utc):
                logger.warning('AgentKit message expired')
                return False
        except (ValueError, TypeError):
            logger.warning('AgentKit invalid expirationTime')
            return False

    # notBefore check (optional)
    not_before_str = payload.get('notBefore')
    if not_before_str:
        try:
            not_before = datetime.fromisoformat(not_before_str)
            if not_before.tzinfo is None:
                not_before = not_before.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < not_before:
                logger.warning('AgentKit message not yet valid')
                return False
        except (ValueError, TypeError):
            logger.warning('AgentKit invalid notBefore')
            return False

    # Nonce replay protection
    nonce = payload.get('nonce', '')
    if not _nonce_cache.check_and_record(nonce):
        logger.warning('AgentKit nonce already used (replay): %s', nonce[:16])
        return False

    return True


# ── Signature verification ─────────────────────────────────────────────────


def _extract_chain_id(chain_id_str: str) -> int:
    """Extract numeric chain ID from CAIP-2 format (e.g., 'eip155:84532' -> 84532)."""
    if ':' in chain_id_str:
        return int(chain_id_str.split(':')[1])
    return int(chain_id_str)


def _verify_eoa_signature(message: str, address: str, signature: str) -> bool:
    """Verify EIP-191 personal_sign (EOA wallets) via ecrecover."""
    try:
        from eth_account.messages import encode_defunct
        from eth_account import Account

        msg_hash = encode_defunct(text=message)
        recovered = Account.recover_message(msg_hash, signature=signature)
        if recovered.lower() != address.lower():
            logger.debug('AgentKit EOA: recovered %s, expected %s', recovered, address)
            return False
        return True
    except Exception as e:
        logger.debug('AgentKit EOA verification error: %s', e)
        return False


def _verify_erc1271_signature(
    message: str, address: str, signature: str, chain_id: int
) -> bool:
    """Verify ERC-1271 signature (smart wallets) via on-chain isValidSignature call."""
    from web3 import Web3
    from eth_account.messages import encode_defunct

    rpc_url = settings.AGENTKIT_RPC_URL
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    msg_hash = encode_defunct(text=message)
    # EIP-191 hash: keccak256("\x19Ethereum Signed Message:\n" + len(message) + message)
    full_hash = w3.keccak(msg_hash.version + msg_hash.header + msg_hash.body)

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(address),
        abi=ERC1271_ABI,
    )
    sig_bytes = bytes.fromhex(
        signature[2:] if signature.startswith('0x') else signature
    )
    logger.info(
        'AgentKit ERC-1271: calling isValidSignature on %s (sig %d bytes, hash %s)',
        address,
        len(sig_bytes),
        full_hash.hex(),
    )
    try:
        result = contract.functions.isValidSignature(
            full_hash,
            sig_bytes,
        ).call()
        valid = result == ERC1271_MAGIC_VALUE
        if not valid:
            logger.warning(
                'AgentKit ERC-1271: contract returned %s, expected %s',
                result.hex(),
                ERC1271_MAGIC_VALUE.hex(),
            )
        return valid
    except Exception as e:
        logger.warning('ERC-1271 check failed for %s: %s', address, e)
        return False


def verify_agentkit_signature(payload: dict) -> str | None:
    """Reconstruct SIWE message from structured fields and verify signature.

    Supports both EOA wallets (EIP-191) and smart wallets (ERC-1271).
    Tries EOA first, falls back to on-chain ERC-1271 verification.
    """
    try:
        from siwe import SiweMessage

        chain_id = _extract_chain_id(payload.get('chainId', ''))
        address = payload['address']
        signature = payload['signature']

        # Reconstruct SIWE message from structured fields (per AgentKit spec)
        siwe_msg = SiweMessage(
            domain=payload['domain'],
            address=address,
            uri=payload['uri'],
            version=payload.get('version', '1'),
            chain_id=chain_id,
            nonce=payload['nonce'],
            issued_at=payload['issuedAt'],
            statement=payload.get('statement'),
            expiration_time=payload.get('expirationTime'),
            not_before=payload.get('notBefore'),
            request_id=payload.get('requestId'),
            resources=payload.get('resources'),
        )
        message_text = siwe_msg.prepare_message()
        logger.info('AgentKit SIWE message:\n%s', message_text)
        logger.info('AgentKit signature (%d chars): %s', len(signature), signature)

        # Try EOA verification first (most common)
        if _verify_eoa_signature(message_text, address, signature):
            return address

        # Fall back to ERC-1271 smart wallet verification
        if _verify_erc1271_signature(message_text, address, signature, chain_id):
            logger.info('AgentKit: verified smart wallet %s via ERC-1271', address)
            return address

        logger.warning('AgentKit: signature verification failed for %s', address)
        return None
    except Exception as e:
        logger.error('AgentKit SIWE verification failed: %s', e)
        return None


# ── AgentBook lookup ───────────────────────────────────────────────────────


def lookup_human(address: str) -> str | None:
    """Call AgentBook.lookupHuman(address) on-chain. Returns hex human_id or None."""
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(settings.AGENTKIT_RPC_URL))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(settings.AGENTKIT_AGENTBOOK_ADDRESS),
            abi=AGENTBOOK_ABI,
        )
        result = contract.functions.lookupHuman(
            Web3.to_checksum_address(address)
        ).call()
        if result == 0:
            return None
        return hex(result)
    except Exception as e:
        logger.error('AgentBook lookup failed: %s', e)
        return None


def is_verified_agent(human_id: str | None) -> bool:
    """Check if a human_id from AgentBook indicates a World ID-verified agent."""
    return human_id is not None
