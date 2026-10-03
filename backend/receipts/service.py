import json
import time
from uuid import uuid4

from fastapi import HTTPException

from backend.crypto.hashing import digest
from backend.crypto.signatures import public_key, sign


class ReceiptService:
    def __init__(self, db, key):
        self.db, self.key = db, key
        self.public_key = public_key(key)

    def get(self, receipt_id):
        with self.db.connect() as conn:
            row = conn.execute("SELECT body FROM receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Receipt not found")
        return json.loads(row["body"])

    def finish(self, action_id, status, reason, evidence):
        # Receipt chain head, insertion and terminal action update are one serialized transaction.
        with self.db.connect(write=True) as conn:
            action = conn.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
            if action["receipt_id"]:
                return json.loads(
                    conn.execute(
                        "SELECT body FROM receipts WHERE receipt_id=?", (action["receipt_id"],)
                    ).fetchone()["body"]
                )
            agent = conn.execute("SELECT * FROM agents WHERE agent_id=?", (action["agent_id"],)).fetchone()
            head = conn.execute(
                "SELECT sequence,receipt_hash FROM receipts WHERE agent_id=? ORDER BY sequence DESC LIMIT 1",
                (action["agent_id"],),
            ).fetchone()
            request = json.loads(action["request"])
            receipt = {
                "schema_version": "poa/1",
                "receipt_id": "poa_" + uuid4().hex,
                "action_id": action_id,
                "request_id": action["request_id"],
                "agent_id": action["agent_id"],
                "agent_name": agent["name"],
                "agent_public_key": agent["public_key"],
                "action": request["action"],
                "requested": request["params"],
                "signed_request": request,
                "network": "solana-devnet",
                "execution_wallet": action["sender"],
                "policy": {
                    "approved": status != "REJECTED",
                    "snapshot": json.loads(action["policy"]),
                    "version": action["policy_version"],
                    "context": json.loads(action["decision_context"]),
                },
                "status": status,
                "reason": reason,
                "result": {
                    "status": {"VERIFIED": "success", "REJECTED": "not_executed", "FAILED": "failed"}[status],
                    "tx_signature": action["tx_signature"],
                },
                "verification": evidence,
                "timestamp": int(time.time()),
                "sequence": head["sequence"] + 1 if head else 1,
                "previous_receipt_hash": head["receipt_hash"] if head else None,
                "poa_public_key": self.public_key,
            }
            receipt["receipt_hash"] = digest(receipt)
            # Sign the 32 digest bytes, NOT their hexadecimal text representation.
            receipt["poa_signature"] = sign(self.key, bytes.fromhex(receipt["receipt_hash"]))
            conn.execute(
                "INSERT INTO receipts VALUES(?,?,?,?,?,?)",
                (
                    receipt["receipt_id"],
                    action["agent_id"],
                    action_id,
                    receipt["sequence"],
                    receipt["receipt_hash"],
                    json.dumps(receipt),
                ),
            )
            # Keep funds reserved on mismatch/unknown outcome. Release only a proven non-transfer.
            if status == "REJECTED" or evidence["status"] in ("not_executed", "failed"):
                conn.execute("UPDATE actions SET reserved_lamports=0 WHERE action_id=?", (action_id,))
            conn.execute(
                "UPDATE actions SET status=?,reason=?,receipt_id=?,completed_at=? WHERE action_id=?",
                (status, reason, receipt["receipt_id"], receipt["timestamp"], action_id),
            )
        return receipt
