# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "web3>=7.0",
#   "eth-account>=0.13",
# ]
# ///
"""
Verify an ERC-1271 smart wallet signature against a SIWE message.

Usage:
    uv run scripts/verify_erc1271_sig.py

Edit the constants below with the values from your test.
"""

from eth_account.messages import encode_defunct
from web3 import Web3

# ── Fill these in from your test ─────────────────────────────────────────────

RPC_URL = 'https://mainnet.base.org'

# Smart account address (from logs: payer wallet)
SMART_ACCOUNT = '0xCCE6A3af2f55e1087C9be9F3c2Ee3634b248fd4C'

# The 192-byte ABI-encoded signature (0x-prefixed hex)
SIGNATURE = (
    '0x'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000040'
    '0000000000000000000000000000000000000000000000000000000000000041'
    '17d70fdf6553ad17e629ad8bbe39ba018c1f506e29e7fc7b1fe207cec0257144'
    '437bf56fda94eccf4ab837cc74b4b1c3403785692af5e44bbf383f62b3149a28'
    '1b'
)

# SIWE message fields (from the agentkit challenge + agent's header)
SIWE_DOMAIN = 'portaldev.simplefi.tech'
SIWE_ADDRESS = SMART_ACCOUNT
SIWE_URI = 'https://portaldev.simplefi.tech/agent/buy-ticket'
SIWE_VERSION = '1'
SIWE_CHAIN_ID = 8453
SIWE_NONCE = '746b99698427b1b085f18d8541c3008f'
SIWE_ISSUED_AT = '2026-03-17T15:08:08Z'
SIWE_RESOURCES = [SIWE_URI]  # ← from challenge info.resources

# ── Script ───────────────────────────────────────────────────────────────────

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
ERC1271_MAGIC = bytes.fromhex('1626ba7e')


def build_siwe_message() -> str:
    """Reconstruct the SIWE message text (EIP-4361 format)."""
    lines = [
        f'{SIWE_DOMAIN} wants you to sign in with your Ethereum account:',
        SIWE_ADDRESS,
        '',
        f'URI: {SIWE_URI}',
        f'Version: {SIWE_VERSION}',
        f'Chain ID: {SIWE_CHAIN_ID}',
        f'Nonce: {SIWE_NONCE}',
        f'Issued At: {SIWE_ISSUED_AT}',
    ]
    if SIWE_RESOURCES:
        lines.append('Resources:')
        for r in SIWE_RESOURCES:
            lines.append(f'- {r}')
    return '\n'.join(lines)


def main():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    print(f'Connected to Base: {w3.is_connected()}')
    print(f'Smart account: {SMART_ACCOUNT}')
    print()

    # Check it's actually a contract
    code = w3.eth.get_code(Web3.to_checksum_address(SMART_ACCOUNT))
    print(f'Contract code size: {len(code)} bytes')
    if len(code) == 0:
        print('ERROR: No contract at this address — not a smart wallet')
        return
    print()

    # Build SIWE message
    message = build_siwe_message()
    print('=== SIWE Message ===')
    print(message)
    print()

    # Compute EIP-191 hash (what personal_sign signs)
    signable = encode_defunct(text=message)
    eip191_hash = w3.keccak(signable.version + signable.header + signable.body)
    print(f'EIP-191 hash: {eip191_hash.hex()}')

    # Also show what the buggy code was computing
    wrong_hash = w3.keccak(signable.body)
    print(f'Wrong hash (body only): {wrong_hash.hex()}')
    print()

    # Decode signature
    sig_bytes = bytes.fromhex(SIGNATURE[2:])
    print(f'Signature length: {len(sig_bytes)} bytes')

    # Extract inner ECDSA sig from ABI encoding
    if len(sig_bytes) == 192:
        inner_len = int.from_bytes(sig_bytes[64:96], 'big')
        inner_sig = sig_bytes[96 : 96 + inner_len]
        r = inner_sig[:32].hex()
        s = inner_sig[32:64].hex()
        v = inner_sig[64]
        print(f'ABI-decoded inner signature: {inner_len} bytes')
        print(f'  r: {r}')
        print(f'  s: {s}')
        print(f'  v: {v} ({hex(v)})')

        # Try to recover the EOA signer from the inner sig
        try:
            from eth_account import Account

            recovered = Account.recover_message(signable, signature=inner_sig)
            print(f'  Recovered EOA signer: {recovered}')
        except Exception as e:
            print(f'  EOA recovery failed: {e}')
    print()

    # Call isValidSignature on-chain
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(SMART_ACCOUNT),
        abi=ERC1271_ABI,
    )

    print('=== ERC-1271 Verification ===')
    print(f'Calling isValidSignature(hash, sig) on {SMART_ACCOUNT}...')
    try:
        result = contract.functions.isValidSignature(eip191_hash, sig_bytes).call()
        if result == ERC1271_MAGIC:
            print(f'Result: {result.hex()} — VALID (magic value matched)')
        else:
            print(f'Result: {result.hex()} — INVALID (expected {ERC1271_MAGIC.hex()})')
    except Exception as e:
        print(f'Call reverted: {e}')

    # Also try with the wrong hash to confirm it matters
    print()
    print('=== Sanity check: wrong hash ===')
    try:
        result2 = contract.functions.isValidSignature(wrong_hash, sig_bytes).call()
        print(f'Result with wrong hash: {result2.hex()}')
    except Exception as e:
        print(f'Call reverted with wrong hash (expected): {e}')


if __name__ == '__main__':
    if not SIWE_NONCE or not SIWE_ISSUED_AT:
        print('ERROR: Fill in SIWE_NONCE and SIWE_ISSUED_AT from the 402 challenge')
        print('       (check server logs or the agent client output)')
    else:
        main()
