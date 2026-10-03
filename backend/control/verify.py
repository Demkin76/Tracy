"""Offline verification pins a separately trusted Tracy key; external truth requires connector readback."""

from backend.control.policy import evaluate
from backend.crypto.hashing import canonical_bytes, digest
from backend.crypto.signatures import verify


def verify_bundle(chain, trusted_key):
    previous, agent_id = None, None
    try:
        for sequence, receipt in enumerate(chain, 1):
            if agent_id is None:
                agent_id = receipt["agent_id"]
            payload = {k: v for k, v in receipt.items() if k not in ("receipt_hash", "poa_signature")}
            request = receipt["intent"]
            unsigned = {k: v for k, v in request.items() if k != "signature"}
            if (
                receipt["schema_version"] != "tracy.receipt/2"
                or receipt["poa_public_key"] != trusted_key
                or receipt["sequence"] != sequence
                or receipt["previous_receipt_hash"] != previous
                or receipt["agent_id"] != agent_id
                or request["agent_id"] != agent_id
                or digest(payload) != receipt["receipt_hash"]
                or digest(unsigned) != receipt["intent_hash"]
                or not verify(trusted_key, receipt["poa_signature"], bytes.fromhex(receipt["receipt_hash"]))
                or not verify(receipt["agent_public_key"], request["signature"], canonical_bytes(unsigned))
            ):
                return {"valid": False, "reason": "signature_hash_identity_or_chain_mismatch"}
            decision, _ = evaluate(receipt["policy"]["snapshot"], request, receipt["policy"]["context"])
            if receipt["status"] == "VERIFIED":
                if decision == "deny" or receipt["verification"]["status"] != "verified":
                    return {"valid": False, "reason": "verified_receipt_policy_mismatch"}
                if decision == "review":
                    approval = receipt["approval"]
                    if (
                        not approval
                        or approval["decision"] != "approve"
                        or approval["intent_hash"] != receipt["intent_hash"]
                        or approval["policy_version"] != receipt["policy"]["version"]
                        or approval["timestamp"] >= approval["expires_at"]
                        or receipt["policy"]["context"]["now"] >= approval["expires_at"]
                    ):
                        return {"valid": False, "reason": "approval_mismatch"}
            if receipt["reason"] == "human_denied" and receipt["approval"]["decision"] != "deny":
                return {"valid": False, "reason": "human_decision_mismatch"}
            previous = receipt["receipt_hash"]
        return {"valid": bool(chain), "reason": "signed_history_verified" if chain else "empty_chain"}
    except (KeyError, TypeError, ValueError):
        return {"valid": False, "reason": "malformed_receipt"}


def verify_events(events, trusted_key):
    previous, agent_id = None, None
    try:
        for sequence, event in enumerate(events, 1):
            if agent_id is None:
                agent_id = event["agent_id"]
            payload = {k: v for k, v in event.items() if k not in ("signature", "event_hash")}
            if (
                event["public_key"] != trusted_key
                or event["agent_id"] != agent_id
                or event["sequence"] != sequence
                or event["previous_hash"] != previous
                or digest(payload) != event["event_hash"]
                or not verify(trusted_key, event["signature"], bytes.fromhex(event["event_hash"]))
            ):
                return False
            previous = event["event_hash"]
        return bool(events)
    except (KeyError, TypeError, ValueError):
        return False
