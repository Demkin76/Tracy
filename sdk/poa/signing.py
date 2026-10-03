import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.actions.models import ActionRequest
from backend.crypto.hashing import canonical_bytes
from backend.crypto.signatures import encode_base64, private_key, public_key, sign


def generate_keypair() -> dict:
    key = Ed25519PrivateKey.generate()
    return {"private_seed": encode_base64(key.private_bytes_raw()), "public_key": public_key(key)}


def sign_request(
    seed, agent_id, recipient, amount, request_id=None, timestamp=None, action="solana.transfer"
):
    request = ActionRequest(
        request_id=request_id or "req_" + uuid4().hex,
        agent_id=agent_id,
        action=action,
        params={"to": recipient, "amount": amount},
        timestamp=int(time.time()) if timestamp is None else timestamp,
        signature="",
    )
    payload = request.unsigned()
    return {**payload, "signature": sign(private_key(seed), canonical_bytes(payload))}
