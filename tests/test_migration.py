import json
import sqlite3

from backend.database.db import Database
from backend.database.models import SCHEMA


def test_legacy_migration_preserves_receipts_and_is_idempotent(env, tmp_path):
    action = env.client.post("/v1/actions", json=env.signed()).json()
    legacy_path = tmp_path / "legacy.sqlite3"
    conn = sqlite3.connect(legacy_path)
    conn.executescript(SCHEMA)
    policy = dict(env.registration["policy"])
    conn.execute(
        "INSERT INTO agents VALUES(?,?,?,?,?)",
        ("agent_test", "Legacy", env.keys["public_key"], 100, json.dumps(policy)),
    )
    # Copy only columns present in the original schema, emulating a pre-account database.
    original = env.db.action(action["action_id"])
    columns = [r[1] for r in conn.execute("PRAGMA table_info(actions)")]
    values = [json.dumps(original[c]) if isinstance(original[c], dict) else original[c] for c in columns]
    conn.execute(f"INSERT INTO actions VALUES({','.join('?' for _ in columns)})", values)
    with env.db.connect() as source:
        receipt_row = tuple(source.execute("SELECT * FROM receipts").fetchone())
    conn.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?)", receipt_row)
    conn.commit()
    conn.close()
    db = Database(legacy_path)
    for _ in range(2):
        db.initialize(action["receipt"]["poa_public_key"], env.gateway.sender)
        with db.connect() as migrated:
            assert tuple(migrated.execute("SELECT * FROM receipts").fetchone()) == receipt_row
            agent = migrated.execute("SELECT * FROM agents").fetchone()
            assert agent["owner_id"] is None
            assert json.loads(agent["policy"])["daily_budget_sol"] == 1.0
            assert migrated.execute("SELECT count(*) FROM policy_versions").fetchone()[0] == 1
            assert migrated.execute("SELECT reserved_lamports FROM actions").fetchone()[0] == 10_000_000
