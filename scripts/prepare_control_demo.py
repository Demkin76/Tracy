"""Create an owner-scoped local control demo; external GitHub and paid APIs are never called."""

import json
import secrets
from pathlib import Path

import httpx

from sdk.poa.signing import generate_keypair
from sdk.tracy import AgentIdentity, Tracy

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    credentials = json.loads((ROOT / "data/tracy-owner.json").read_text())
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=30) as owner:
        response = owner.post(
            "/v1/auth/login", json={"email": credentials["email"], "password": credentials["password"]}
        )
        response.raise_for_status()
        account = response.json()
        owner.headers["X-CSRF-Token"] = account["csrf_token"]
        who = account["user"]["user_id"]
        path = ROOT / "data/control-credentials.json"
        saved = json.loads(path.read_text()) if path.exists() else {}
        saved.setdefault("TRACY_LOCAL_PROVIDER_TOKEN", secrets.token_urlsafe(32))
        path.write_text(json.dumps(saved, indent=2))
        resources = [
            {
                "id": "demo-records",
                "kind": "database",
                "label": "Local controlled database",
                "path": str(ROOT / "data/control-records.sqlite3"),
                "owner_ids": [who],
            },
            {
                "id": "demo-api",
                "kind": "http",
                "label": "Local API simulator (no real billing)",
                "owner_ids": [who],
                "base_url": "http://127.0.0.1:8011",
                "local_test": True,
                "token_env": "TRACY_LOCAL_PROVIDER_TOKEN",
                "operation": "generate",
                "asset": "test-credit",
                "units_per_call": 10,
                "allowed_fields": ["prompt"],
                "required_fields": ["prompt"],
            },
            {
                "id": "demo-github",
                "kind": "github",
                "label": "Local GitHub simulator (no real PR)",
                "owner_ids": [who],
                "base_url": "http://127.0.0.1:8011",
                "local_test": True,
                "token_env": "TRACY_LOCAL_PROVIDER_TOKEN",
                "repository": "tracy/demo",
            },
        ]
        path = ROOT / "data/control-resources.json"
        previous = json.loads(path.read_text())["resources"] if path.exists() else []
        ids = {r["id"] for r in resources}
        if any(r["id"] in ids and r.get("owner_ids") != [who] for r in previous):
            raise RuntimeError("Demo resource ID belongs to another workspace")
        path.write_text(
            json.dumps({"resources": [r for r in previous if r["id"] not in ids] + resources}, indent=2)
        )
        key_path = ROOT / "data/control-demo-agent.json"
        if key_path.exists():
            identity = json.loads(key_path.read_text())
        else:
            identity = {**generate_keypair(), "agent_id": "tracy_control_demo"}
            r = owner.post(
                "/v2/agents",
                json={
                    "agent_id": identity["agent_id"],
                    "public_key": identity["public_key"],
                    "name": "Tracy control demo",
                },
            )
            r.raise_for_status()
            key_path.write_text(json.dumps(identity, indent=2))
        aid = identity["agent_id"]
        policy = {
            "rules": [
                {
                    "action": "database.insert",
                    "resource_id": "demo-records",
                    "allowed_targets": ["tracy_records"],
                    "max_units_per_action": 1,
                    "daily_units": 100,
                    "require_approval": True,
                },
                {
                    "action": "http.invoke",
                    "resource_id": "demo-api",
                    "allowed_targets": ["generate"],
                    "max_units_per_action": 10,
                    "daily_units": 1000,
                    "require_approval": False,
                },
                {
                    "action": "github.pull_request",
                    "resource_id": "demo-github",
                    "allowed_targets": ["tracy/demo"],
                    "max_units_per_action": 1,
                    "daily_units": 100,
                    "require_approval": True,
                },
            ],
            "review_new_targets": False,
            "max_per_minute": 30,
            "max_denials_per_hour": 20,
            "approval_ttl_seconds": 86400,
        }
        current = owner.get("/v2/agents/" + aid + "/policy").json()
        if current["policy"] != policy:
            r = owner.put(
                "/v2/agents/" + aid + "/policy",
                json={"expected_version": current["version"], "policy": policy},
            )
            r.raise_for_status()
        task = owner.post(
            "/v2/tasks",
            json={
                "agent_id": aid,
                "purpose": "Demonstrate controlled database writes, API calls and draft PRs on local test services",
                "allowed_resources": ["demo-records", "demo-api", "demo-github"],
                "allowed_actions": ["database.insert", "http.invoke", "github.pull_request"],
                "expires_in_seconds": 604800,
            },
        )
        task.raise_for_status()
        task_id = task.json()["task_id"]
        client = Tracy(task_id=task_id)
        guarded = client.protect(AgentIdentity(aid, identity["private_seed"]))
        items = [
            guarded.intent(
                "database.insert",
                "demo-records",
                {"record": {"message": "Approved task result", "test_only": True}},
                reason="Store a test result",
            ),
            guarded.intent(
                "http.invoke",
                "demo-api",
                {"prompt": "Summarize the approved local test task"},
                reason="Call an operator-approved API",
            ),
            guarded.intent(
                "github.pull_request",
                "demo-github",
                {
                    "head": "demo-change",
                    "base": "main",
                    "head_sha": "a" * 40,
                    "title": "Tracy controlled change",
                    "body": "Local simulated draft PR; no external GitHub action",
                },
                reason="Request review of the pinned change",
            ),
            guarded.intent(
                "database.insert",
                "demo-records",
                {"sql": "DROP TABLE users"},
                reason="Demonstrate blocked unsupported parameters",
            ),
        ]
        client.close()
        report = {
            "agent_id": aid,
            "task_id": task_id,
            "intents": [{"id": i["intent_id"], "action": i["action"], "status": i["status"]} for i in items],
        }
        (ROOT / "data/control-demo.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))


if __name__ == "__main__":
    prepare()
