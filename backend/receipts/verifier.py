import json
from decimal import Decimal

from backend.crypto.hashing import canonical_bytes, digest, receipt_payload
from backend.crypto.signatures import verify
from backend.policies.engine import evaluate


def verify_receipt_crypto(receipt: dict, trusted_public_key: str) -> tuple[bool, bool]:
    try:
        hash_valid = digest(receipt_payload(receipt)) == receipt["receipt_hash"]
        signature_valid = receipt["poa_public_key"] == trusted_public_key and verify(
            trusted_public_key, receipt["poa_signature"], bytes.fromhex(receipt["receipt_hash"])
        )
        return hash_valid, signature_valid
    except (KeyError, TypeError, ValueError):
        return False, False


def verify_chain(receipts: list[dict], trusted_public_key: str, agent_id: str) -> bool:
    previous = None
    for sequence, receipt in enumerate(receipts, 1):
        if (
            receipt.get("agent_id") != agent_id
            or receipt.get("sequence") != sequence
            or receipt.get("previous_receipt_hash") != previous
            or not all(verify_receipt_crypto(receipt, trusted_public_key))
        ):
            return False
        previous = receipt["receipt_hash"]
    return bool(receipts)


class ReceiptVerifier:
    def __init__(self, db, receipts, gateway):
        self.db, self.receipts, self.gateway = db, receipts, gateway

    async def verify(self, receipt_id):
        receipt = self.receipts.get(receipt_id)
        key = self.receipts.public_key
        hash_valid, signature_valid = verify_receipt_crypto(receipt, key)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT body FROM receipts WHERE agent_id=? AND sequence<=? ORDER BY sequence",
                (receipt["agent_id"], receipt["sequence"]),
            ).fetchall()
        chain = [json.loads(row["body"]) for row in rows]
        chain_valid = (
            verify_chain(chain, key, receipt["agent_id"])
            and chain[-1]["receipt_id"] == receipt_id
            and len(chain) == receipt["sequence"]
        )
        request = receipt["signed_request"]
        unsigned = {k: v for k, v in request.items() if k != "signature"}
        request_valid = (
            verify(receipt["agent_public_key"], request["signature"], canonical_bytes(unsigned))
            and request["agent_id"] == receipt["agent_id"]
            and request["request_id"] == receipt["request_id"]
            and request["action"] == receipt["action"]
            and request["params"] == receipt["requested"]
        )
        evidence_valid, evidence_status = None, "not_applicable"
        if hash_valid and signature_valid and request_valid:
            approved, reason = evaluate(
                receipt["action"],
                receipt["requested"],
                receipt["policy"]["snapshot"],
                receipt["execution_wallet"],
                receipt["policy"].get("context"),
            )
            if receipt["status"] == "REJECTED":
                evidence_valid = (
                    not approved
                    and receipt["policy"]["approved"] is False
                    and reason == receipt["reason"]
                    and receipt["result"]["tx_signature"] is None
                )
                evidence_status = "policy_rejection_verified" if evidence_valid else "policy_mismatch"
            elif receipt["result"]["tx_signature"]:
                evidence = await self.gateway.verify_transfer(
                    receipt["result"]["tx_signature"],
                    receipt["execution_wallet"],
                    receipt["requested"]["to"],
                    int(Decimal(str(receipt["requested"]["amount"])) * 1_000_000_000),
                    digest(unsigned),
                )
                evidence_status = evidence.status
                if evidence.status not in ("pending", "unavailable"):
                    evidence_valid = (
                        approved
                        and receipt["policy"]["approved"] is True
                        and receipt["network"] == "solana-devnet"
                        and receipt["status"] == "VERIFIED"
                        and evidence.status == "verified"
                    )
        return {
            "valid": hash_valid
            and signature_valid
            and request_valid
            and chain_valid
            and evidence_valid is True,
            "hash_valid": hash_valid,
            "signature_valid": signature_valid,
            "request_signature_valid": request_valid,
            "chain_valid": chain_valid,
            "evidence_valid": evidence_valid,
            "evidence_status": evidence_status,
            "receipt_status": receipt["status"],
        }
