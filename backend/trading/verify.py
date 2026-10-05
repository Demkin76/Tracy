"""Offline TradingReceipt verification. Paper receipts never prove on-chain execution."""

from backend.crypto.hashing import canonical_bytes, digest
from backend.crypto.signatures import verify


def valid_receipt(proof, trusted_key):
    try:
        body = {k: v for k, v in proof.items() if k not in ("receipt_hash", "signature")}
        intent = proof["intent"]
        order = intent["params"]
        trade = proof["trade"]
        unsigned = {k: v for k, v in intent.items() if k != "signature"}
        approval = proof["approval"]
        authorized = proof["policy"]["context"]["notional"] <= proof["policy"]["snapshot"][
            "human_approval_above"
        ] or (
            approval
            and approval["decision"] == "approve"
            and approval["intent_hash"] == proof["intent_hash"]
            and approval["policy_version"] == proof["strategy_version"]
            and approval["timestamp"] < approval["expires_at"]
        )
        return bool(
            proof["schema_version"] == "tracy.trading-receipt/3"
            and proof["public_key"] == trusted_key
            and digest(body) == proof["receipt_hash"]
            and verify(trusted_key, proof["signature"], bytes.fromhex(proof["receipt_hash"]))
            and digest(unsigned) == proof["intent_hash"]
            and verify(proof["decision_public_key"], intent["signature"], canonical_bytes(unsigned))
            and intent["agent_id"] == proof["agent_id"] == trade["agent_id"]
            and intent["resource_id"] == proof["strategy_id"] == trade["strategy_id"]
            and order["strategy_version"] == proof["strategy_version"] == trade["strategy_version"]
            and order["side"] == trade["side"]
            and order["quantity"] == trade["quantity"]
            and order["requested_price"] == trade["requested_price"]
            and trade["trade_id"] == proof["trade_id"]
            and proof["execution"]["mode"] == "paper"
            and proof["execution"]["on_chain"] is False
            and trade["tx_signature"] is None
            and proof["policy"]["allowed"] is True
            and authorized
        )
    except (ValueError, KeyError, TypeError):
        return False


def verify_chain(chain, trusted_key):
    previous = None
    for index, proof in enumerate(chain, 1):
        if (
            not valid_receipt(proof, trusted_key)
            or proof["sequence"] != index
            or proof["previous_receipt_hash"] != previous
        ):
            return False
        previous = proof["receipt_hash"]
    return True
