"""Read-only v3 acceptance checks against the running local deployment."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx

from backend.config import Settings
from backend.trading.verify import verify_chain


def main():
    credentials = json.loads(Path("data/tracy-owner.json").read_text(encoding="utf-8"))
    demos = json.loads(Path("data/trading-demo.json").read_text(encoding="utf-8"))
    results = []
    with sqlite3.connect(Settings().database_path) as db:
        trusted = db.execute("SELECT value FROM metadata WHERE key='poa_public_key'").fetchone()[0]
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60) as client:
        login = client.post("/v1/auth/login", json={k: credentials[k] for k in ("email", "password")})
        login.raise_for_status()
        assert client.get("/v1/config").json()["version"] == "3.0.0"
        for demo in demos:
            sid = demo["strategy_id"]
            response = client.get("/v1/strategies/" + sid)
            response.raise_for_status()
            s = response.json()
            performance = client.get("/v1/strategies/" + sid + "/performance").json()
            assert performance["performance_gap"] == round(
                performance["live_return"] - performance["backtest_return"], 6
            )
            fills = client.get("/v1/strategies/" + sid + "/trades").json()["items"]
            assert fills
            bundle = client.get("/v1/trades/" + fills[0]["trade_id"] + "/proof").json()
            assert (
                bundle["checks"]["valid"]
                and bundle["checks"]["readback_matches"]
                and not bundle["checks"]["on_chain"]
            )
            assert verify_chain(bundle["chain"], trusted)
            assert all(p["trade"]["tx_signature"] is None for p in bundle["chain"])
            results.append(
                {
                    "strategy_id": sid,
                    "verified_fills": len(fills),
                    "health": s["health"]["status"],
                    "score": s["health"]["score"],
                    "backtest_return": performance["backtest_return"],
                    "paper_live_return": performance["live_return"],
                }
            )
            if demo == demos[0]:
                Path("data/trading-proof-live.json").write_text(
                    json.dumps(bundle, indent=2), encoding="utf-8"
                )
                target = fills[0]["intent_id"]
                deployment = performance["deployment"]["deployment_id"]
        public = client.get(
            "/v1/public/trading/compare", params={"ids": ",".join(d["strategy_id"] for d in demos)}
        )
        public.raise_for_status()
        assert len(public.json()["items"]) == 2
        for demo in demos:
            # New strategy publication does not opt the original action history into the old catalog.
            assert not client.get("/v1/agents/" + demo["agent_id"]).json()["listed"]
        offline = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.verify_trading",
                "data/trading-proof-live.json",
                "--public-key",
                trusted,
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        assert json.loads(offline.stdout)["valid"]
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "v3-check", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tracy_market_context", "arguments": {"strategy_id": demos[0]["strategy_id"]}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "tracy_status", "arguments": {"intent_id": target}},
        },
    ]
    env = {
        k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP")
    }
    env.update(
        TRACY_BASE_URL="http://127.0.0.1:8000",
        TRACY_TASK_ID=deployment,
        TRACY_AGENT_KEY_FILE=str(Path("data/tracy_v3_momentum.json").resolve()),
    )
    process = subprocess.run(
        [sys.executable, "-m", "sdk.tracy.mcp"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=30,
        env=env,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4]
    assert not replies[2]["result"]["isError"] and not replies[3]["result"]["isError"]
    assert json.loads(replies[2]["result"]["content"][0]["text"])["mode"] == "paper"
    assert json.loads(replies[3]["result"]["content"][0]["text"])["status"] == "VERIFIED"
    preserved = {}
    with (
        sqlite3.connect("data/backups/before-tracy-v3-20261003.sqlite3") as before,
        sqlite3.connect(Settings().database_path) as after,
    ):
        for table, key in (
            ("receipts", "receipt_id"),
            ("control_receipts", "receipt_id"),
            ("control_events", "event_hash"),
        ):
            rows = before.execute(f"SELECT {key},body FROM {table}").fetchall()
            for identity, body in rows:
                assert after.execute(f"SELECT body FROM {table} WHERE {key}=?", (identity,)).fetchone() == (
                    body,
                )
            preserved[table] = len(rows)
    report = {
        "version": "3.0.0",
        "strategies": results,
        "mcp_quote_and_status": True,
        "offline_proof_valid": True,
        "public_compare": True,
        "legacy_publication_unchanged": True,
        "original_records_unchanged": preserved,
    }
    Path("data/trading-live-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
