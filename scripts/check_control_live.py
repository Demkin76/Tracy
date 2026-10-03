"""Read-only live checks: subprocess MCP, signed bundles, original receipt preservation."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx

from backend.config import Settings
from backend.control.verify import verify_bundle, verify_events


def main():
    demo = json.loads(Path("data/control-demo.json").read_text(encoding="utf-8"))
    credentials = json.loads(Path("data/tracy-owner.json").read_text(encoding="utf-8"))
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as client:
        login = client.post("/v1/auth/login", json={k: credentials[k] for k in ("email", "password")})
        login.raise_for_status()
        config = client.get("/v1/config").json()
        bundle_response = client.get("/v2/agents/" + demo["agent_id"] + "/export")
        bundle_response.raise_for_status()
        bundle = bundle_response.json()
        # Pin the deployment key directly from its local database, not from the untrusted bundle.
        with sqlite3.connect(Settings().database_path) as db:
            key = db.execute("SELECT value FROM metadata WHERE key='poa_public_key'").fetchone()[0]
        assert verify_bundle(bundle["receipts"], key)["valid"]
        assert verify_events(bundle["items"], key)
        Path("data/control-audit-verified.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        offline = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.verify_control",
                "data/control-audit-verified.json",
                "--public-key",
                key,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        assert json.loads(offline.stdout)["audit_chain_valid"]
        live = []
        for item in demo["intents"]:
            intent = client.get("/v2/intents/" + item["id"]).json()
            if intent["status"] == "VERIFIED":
                check = client.get("/v2/intents/" + item["id"] + "/verify")
                check.raise_for_status()
                assert check.json()["verified_result"], check.text
            live.append({"action": item["action"], "status": intent["status"]})
    target = demo["intents"][1]["id"]
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "tracy-check", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tracy_status", "arguments": {"intent_id": target}},
        },
    ]
    # Explicit child environment. No inherited owner/provider tokens.
    env = {
        k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
    }
    env.update(
        TRACY_BASE_URL="http://127.0.0.1:8000",
        TRACY_TASK_ID=demo["task_id"],
        TRACY_AGENT_KEY_FILE=str(Path("data/control-demo-agent.json").resolve()),
    )
    process = subprocess.run(
        [sys.executable, "-m", "sdk.tracy.mcp"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=True,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(responses) == 3 and responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == {"tracy_intent", "tracy_status"}
    assert not responses[2]["result"]["isError"]
    assert json.loads(responses[2]["result"]["content"][0]["text"])["intent_id"] == target
    old = Path("data/backups/before-control-layer-20260927.sqlite3")
    preserved = None
    if old.exists():
        with sqlite3.connect(old) as before, sqlite3.connect(Settings().database_path) as after:
            originals = before.execute("SELECT receipt_id,body FROM receipts").fetchall()
            for receipt_id, body in originals:
                assert after.execute(
                    "SELECT body FROM receipts WHERE receipt_id=?", (receipt_id,)
                ).fetchone() == (body,)
            preserved = len(originals)
    report = {
        "version": config["version"],
        "live_outcomes": live,
        "mcp_subprocess_passed": True,
        "offline_receipts_and_audit_valid": True,
        "original_receipts_unchanged": preserved,
    }
    Path("data/control-live-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
