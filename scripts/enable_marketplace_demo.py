"""Enable documented payout recipes on the two existing demonstration profiles."""

import json
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
credentials = json.loads((root / "data/tracy-owner.json").read_text(encoding="utf-8"))
report = {}
with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:
    auth = client.post(
        "/v1/auth/login", json={"email": credentials["email"], "password": credentials["password"]}
    )
    auth.raise_for_status()
    client.headers["X-CSRF-Token"] = auth.json()["csrf_token"]
    agents = client.get("/v1/agents").json()["items"]
    for prefix, kind in (("tracy_atlas_", "batch_payout"), ("tracy_sentinel_", "scheduled_payout")):
        matches = [a for a in agents if a["agent_id"].startswith(prefix) and a["listed"]]
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one published demo profile for " + prefix)
        agent = matches[0]
        path = "/v1/agents/" + agent["agent_id"] + "/offer"
        current = client.get(path).json()["offer"]
        if not current or current["kind"] != kind or not current["enabled"]:
            response = client.put(path, json={"kind": kind, "enabled": True})
            response.raise_for_status()
        report[kind] = agent["agent_id"]
(root / "data/marketplace-demo.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
