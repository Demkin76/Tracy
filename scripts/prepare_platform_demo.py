"""Prepare two clearly labeled Devnet demonstration agents with real evidence."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

from sdk.poa import PoAClient, generate_keypair


def main():
    root = Path("data")
    owner = json.loads((root / "tracy-owner.json").read_text(encoding="utf-8"))
    recipient = json.loads((root / "presentation-recipient.json").read_text(encoding="utf-8"))["public_key"]
    keys_path = root / "platform-demo-keys.json"
    if not keys_path.exists():
        with keys_path.open("x", encoding="utf-8") as f:
            json.dump(
                {
                    name: {**generate_keypair(), "agent_id": "tracy_" + name + "_" + uuid4().hex[:12]}
                    for name in ("atlas", "sentinel")
                },
                f,
                indent=2,
            )
    keys = json.loads(keys_path.read_text(encoding="utf-8"))
    report = {"started_at": int(time.time()), "agents": [], "actions": []}
    report_path = root / "platform-demo-report.json"

    def save():
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as owner_client:
        login = owner_client.post("/v1/auth/login", json={k: owner[k] for k in ("email", "password")})
        login.raise_for_status()
        owner_client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        issued = owner_client.post("/v1/account/api-keys", json={"name": "Platform demo preparation"})
        issued.raise_for_status()
        key = issued.json()
        try:
            with PoAClient(api_key=key["token"]) as tracy:
                for slug in ("atlas", "sentinel"):
                    identity = keys[slug]
                    try:
                        agent = tracy.agent(identity["agent_id"])
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code != 404:
                            raise
                        agent = tracy.register(
                            identity["agent_id"],
                            "Atlas - Devnet payouts" if slug == "atlas" else "Sentinel - policy checks",
                            identity["public_key"],
                            {
                                "allowed_actions": ["solana.transfer"],
                                "max_transfer_sol": 0.01,
                                "daily_budget_sol": 0.05,
                                "allowed_recipients": [recipient],
                            },
                            "Demonstration SDK agent. Executes small, signed Devnet payouts with a fixed recipient and budget."
                            if slug == "atlas"
                            else "Demonstration policy agent. Records intentionally blocked test requests alongside one permitted Devnet payout.",
                        )
                    report["agents"].append({"agent_id": agent["agent_id"], "name": agent["name"]})

                    def fresh_check(receipt_id):
                        for attempt in range(5):
                            check = tracy.verify(receipt_id)
                            if check["valid"]:
                                return check
                            if check["evidence_valid"] is not None:
                                raise RuntimeError("Receipt verification failed: " + json.dumps(check))
                            time.sleep(2 + attempt)
                        raise RuntimeError("RPC evidence remains unavailable; rerun the same saved demo jobs")

                    count = 5 if slug == "atlas" else 1
                    for i in range(count):
                        result = tracy.payout(
                            identity["private_seed"],
                            identity["agent_id"],
                            recipient,
                            0.000001,
                            f"platform_{slug}_payout_{i + 1:03d}",
                        )
                        for _ in range(10):
                            if result["receipt_id"]:
                                break
                            time.sleep(2)
                            result = tracy.reconcile(result["action_id"])
                        report["actions"].append(result)
                        save()
                        if result["status"] != "VERIFIED":
                            raise RuntimeError(
                                "Devnet demonstration payout is not confirmed; inspect the report"
                            )
                        fresh_check(result["receipt_id"])
                    for i in range(2 if slug == "sentinel" else 1):
                        result = tracy.payout(
                            identity["private_seed"],
                            identity["agent_id"],
                            recipient,
                            1,
                            f"platform_{slug}_refusal_{i + 1:03d}",
                        )
                        assert result["status"] == "REJECTED"
                        report["actions"].append(result)
                        save()
                    tracy.publish(
                        identity["agent_id"],
                        disclose_history=True,
                        category="payouts" if slug == "atlas" else "automation",
                        tagline="Bounded payouts. Signed intent. Public evidence."
                        if slug == "atlas"
                        else "Policy refusals are part of the record.",
                    )
                    report["agents"][-1]["public_path"] = "/a/" + identity["agent_id"]
                assert len(tracy.catalog(query="Devnet payouts")["items"]) >= 1
                proof = next(a for a in report["actions"] if a["status"] == "VERIFIED")
                share = tracy.share(proof["receipt_id"], disclose_receipt=True, expires_days=7)
                report["shared_proof_path"] = share["path"]
                with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as guest:
                    verify = guest.get("/v1/public/proofs/" + share["share_id"] + "/verify")
                    verify.raise_for_status()
                    assert verify.json()["valid"]
                report["passed"] = True
                save()
                print(
                    json.dumps(
                        {
                            "passed": True,
                            "agents": report["agents"],
                            "shared_proof_path": share["path"],
                            "verified": sum(a["status"] == "VERIFIED" for a in report["actions"]),
                            "rejected": sum(a["status"] == "REJECTED" for a in report["actions"]),
                        },
                        indent=2,
                    )
                )
        finally:
            owner_client.delete("/v1/account/api-keys/" + key["key_id"]).raise_for_status()
            save()


if __name__ == "__main__":
    main()
