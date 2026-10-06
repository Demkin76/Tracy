import base64
import json

from fastapi import HTTPException

from backend.blockchain.solana import PreparedTransfer


class DevnetAnchors:
    def __init__(self, adaptive, gateway):
        self.a, self.db, self.gateway = adaptive, adaptive.db, gateway

    async def anchor(self, bid, owner_id):
        if not self.a.s.settings.adaptive_devnet_anchors_enabled:
            raise HTTPException(
                409,
                "Devnet anchoring is disabled on this server. Enable it on the devnet deployment and fund its wallet with test SOL.",
            )
        with self.db.connect() as conn:
            bundle = conn.execute(
                "SELECT * FROM adaptive_bundles WHERE bundle_id=? AND owner_id=?", (bid, owner_id)
            ).fetchone()
            prior = conn.execute("SELECT * FROM adaptive_anchors WHERE bundle_id=?", (bid,)).fetchone()
        if not bundle:
            raise HTTPException(404, "Bundle not found")
        self.a.checked(json.loads(bundle["body"]))
        if prior and prior["status"] == "CONFIRMED":
            return self.a.get_bundle(bid, owner_id)
        try:
            if not prior:
                prepared = await self.gateway.prepare_memo(bundle["bundle_hash"])
                with self.db.connect(write=True) as conn:
                    # Concurrent requests retain one exact signed transaction.
                    conn.execute(
                        "INSERT OR IGNORE INTO adaptive_anchors VALUES(?,?,?,'PENDING',?)",
                        (
                            bid,
                            prepared.signature,
                            base64.b64encode(prepared.raw).decode(),
                            json.dumps(
                                {
                                    "network": "solana-devnet",
                                    "bundle_hash": bundle["bundle_hash"],
                                    "meaning": "Timestamped hash, not proof of trading profitability or exchange execution",
                                }
                            ),
                        ),
                    )
                    prior = conn.execute(
                        "SELECT * FROM adaptive_anchors WHERE bundle_id=?", (bid,)
                    ).fetchone()
            checked = await self.gateway.verify_memo(prior["signature"], bundle["bundle_hash"])
            if checked["status"] == "PENDING":
                await self.gateway.broadcast(
                    PreparedTransfer(base64.b64decode(prior["raw_tx"]), prior["signature"])
                )
                checked = await self.gateway.verify_memo(prior["signature"], bundle["bundle_hash"])
            metadata = {
                **json.loads(prior["body"]),
                **checked,
                "explorer": "https://explorer.solana.com/tx/" + prior["signature"] + "?cluster=devnet",
            }
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "UPDATE adaptive_anchors SET status=?,body=? WHERE bundle_id=?",
                    (checked["status"], json.dumps(metadata), bid),
                )
        except Exception as exc:
            raise HTTPException(
                503,
                "Devnet memo not confirmed. Check RPC access and test-SOL balance; retry verifies the same transaction without inventing a proof.",
            ) from exc
        return self.a.get_bundle(bid, owner_id)
