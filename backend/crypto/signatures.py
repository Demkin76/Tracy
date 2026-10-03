import base64
import binascii

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def decode_base64(value: str, size: int) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid base64 encoding") from exc
    if len(raw) != size:
        raise ValueError(f"Expected {size} bytes")
    return raw


def encode_base64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def private_key(seed: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(decode_base64(seed, 32))


def public_key(key: Ed25519PrivateKey) -> str:
    return encode_base64(key.public_key().public_bytes_raw())


def sign(key: Ed25519PrivateKey, message: bytes) -> str:
    return encode_base64(key.sign(message))


def verify(key: str, signature: str, message: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(decode_base64(key, 32)).verify(
            decode_base64(signature, 64), message
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
