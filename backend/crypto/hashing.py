import hashlib

import rfc8785


def canonical_bytes(value: dict) -> bytes:
    """RFC 8785 / JCS, shared by Python SDK and browser WebCrypto client."""
    return rfc8785.dumps(value)


def digest(value: dict) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def receipt_payload(receipt: dict) -> dict:
    return {k: v for k, v in receipt.items() if k not in ("receipt_hash", "poa_signature")}
