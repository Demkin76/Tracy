from typing import Literal

from pydantic import BaseModel


class VerificationResult(BaseModel):
    valid: bool
    hash_valid: bool
    signature_valid: bool
    request_signature_valid: bool
    chain_valid: bool
    evidence_valid: bool | None
    evidence_status: str
    receipt_status: Literal["VERIFIED", "REJECTED", "FAILED"]
