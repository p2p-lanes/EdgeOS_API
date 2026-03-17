# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "web3>=7.0",
#   "eth-account>=0.13",
#   "siwe>=4.0",
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

# Smart account address (from AGENTKIT header, NOT the x402 payer)
SMART_ACCOUNT = '0x7810905860A7E7e5981Fd99cB324444190745D3E'

# The 192-byte ABI-encoded signature (0x-prefixed hex)
# Paste the signature from the AGENTKIT header here
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
SIWE_NONCE = 'a1959847f21f7827d6e0f97bc6943d10'
SIWE_ISSUED_AT = '2026-03-17T15:26:37Z'
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


def build_siwe_message_manual() -> str:
    """Reconstruct the SIWE message text manually (EIP-4361 format)."""
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


def build_siwe_message_library() -> str:
    """Reconstruct using Python siwe library (same as server)."""
    from siwe import SiweMessage

    siwe_msg = SiweMessage(
        domain=SIWE_DOMAIN,
        address=SIWE_ADDRESS,
        uri=SIWE_URI,
        version=SIWE_VERSION,
        chain_id=SIWE_CHAIN_ID,
        nonce=SIWE_NONCE,
        issued_at=SIWE_ISSUED_AT,
        resources=SIWE_RESOURCES,
    )
    return siwe_msg.prepare_message()


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

    # Build SIWE message both ways
    msg_manual = build_siwe_message_manual()
    msg_library = build_siwe_message_library()

    print('=== SIWE Message (python siwe library — same as server) ===')
    print(msg_library)
    print()

    if msg_manual == msg_library:
        print('Manual and library messages MATCH')
    else:
        print('!!! MISMATCH between manual and library messages !!!')
        print()
        print('=== SIWE Message (manual) ===')
        print(msg_manual)
        print()
        print('=== Diff (repr) ===')
        for i, (a, b) in enumerate(zip(msg_manual, msg_library)):
            if a != b:
                print(f'  First diff at char {i}: manual={repr(a)} library={repr(b)}')
                print(
                    f'  Context manual:  ...{repr(msg_manual[max(0, i - 20) : i + 20])}...'
                )
                print(
                    f'  Context library: ...{repr(msg_library[max(0, i - 20) : i + 20])}...'
                )
                break
        if len(msg_manual) != len(msg_library):
            print(f'  Length: manual={len(msg_manual)} library={len(msg_library)}')
    print()

    # Use library message (matches server)
    message = msg_library

    # Compute EIP-191 hash (what personal_sign signs)
    signable = encode_defunct(text=message)
    eip191_hash = w3.keccak(signable.version + signable.header + signable.body)
    print(f'EIP-191 hash (library): {eip191_hash.hex()}')

    # Compare with server's logged hash
    SERVER_HASH = '2c00773e0b89cca1771cc75293ae3beef7844cf3b99a3d24fd5e8dff5c2c8f2d'
    print(f'Server logged hash:     {SERVER_HASH}')
    print(f'Hashes match: {eip191_hash.hex() == SERVER_HASH}')
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
