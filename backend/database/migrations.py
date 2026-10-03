"""Additive, transactional week-one migration. Existing signed receipts stay byte-for-byte intact."""

import json
from datetime import datetime, timezone
from decimal import Decimal

AUTH_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
user_id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
password_hash TEXT NOT NULL, created_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sessions (
token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id),
csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS api_keys (
key_id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL REFERENCES users(user_id),
name TEXT NOT NULL, prefix TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
revoked_at INTEGER)""",
    """CREATE TABLE IF NOT EXISTS auth_attempts (bucket TEXT NOT NULL, timestamp INTEGER NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS auth_attempts_bucket ON auth_attempts(bucket,timestamp)""",
    """CREATE TABLE IF NOT EXISTS policy_versions (
agent_id TEXT NOT NULL REFERENCES agents(agent_id), version INTEGER NOT NULL, body TEXT NOT NULL,
created_at INTEGER NOT NULL, created_by TEXT REFERENCES users(user_id), PRIMARY KEY(agent_id,version))""",
    """CREATE TRIGGER IF NOT EXISTS policy_no_update BEFORE UPDATE ON policy_versions
BEGIN SELECT RAISE(ABORT, 'Policy versions are append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS policy_no_delete BEFORE DELETE ON policy_versions
BEGIN SELECT RAISE(ABORT, 'Policy versions are append-only'); END""",
]


def migrate(conn):
    for statement in AUTH_SCHEMA:
        conn.execute(statement)
    columns = {
        "agents": {
            "owner_id": "TEXT REFERENCES users(user_id)",
            "description": "TEXT NOT NULL DEFAULT ''",
            "active": "INTEGER NOT NULL DEFAULT 1",
            "policy_version": "INTEGER NOT NULL DEFAULT 1",
        },
        "actions": {
            "policy_version": "INTEGER NOT NULL DEFAULT 1",
            "decision_context": "TEXT NOT NULL DEFAULT '{}'",
            "reserved_lamports": "INTEGER NOT NULL DEFAULT 0",
            "budget_day": "TEXT",
        },
    }
    for table, additions in columns.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in additions.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    conn.execute("CREATE INDEX IF NOT EXISTS agents_owner ON agents(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS action_budgets ON actions(agent_id,budget_day,status)")
    for row in conn.execute("SELECT * FROM agents").fetchall():
        policy = json.loads(row["policy"])
        policy.setdefault("daily_budget_sol", 1.0)
        conn.execute("UPDATE agents SET policy=? WHERE agent_id=?", (json.dumps(policy), row["agent_id"]))
        conn.execute(
            "INSERT OR IGNORE INTO policy_versions VALUES(?,?,?,?,?)",
            (row["agent_id"], row["policy_version"], json.dumps(policy), row["created_at"], row["owner_id"]),
        )
    # Bootstrap conservative debits from pre-migration actions; never rewrite their receipts.
    for row in conn.execute("SELECT * FROM actions WHERE budget_day IS NULL").fetchall():
        amount = json.loads(row["request"])["params"]["amount"]
        reserved = (
            int(Decimal(str(amount)) * 1_000_000_000)
            if row["status"] in ("VERIFIED", "PENDING", "PREPARING")
            else 0
        )
        day = datetime.fromtimestamp(row["created_at"], timezone.utc).date().isoformat()
        conn.execute(
            "UPDATE actions SET budget_day=?,reserved_lamports=? WHERE action_id=?",
            (day, reserved, row["action_id"]),
        )
    conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','2')")
