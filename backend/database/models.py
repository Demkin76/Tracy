SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY, name TEXT NOT NULL, public_key TEXT NOT NULL,
    created_at INTEGER NOT NULL, policy TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
    action_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    request_id TEXT NOT NULL, request TEXT NOT NULL, policy TEXT NOT NULL,
    sender TEXT NOT NULL, status TEXT NOT NULL, reason TEXT,
    tx_signature TEXT, receipt_id TEXT, created_at INTEGER NOT NULL,
    UNIQUE(agent_id, request_id)
);
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(agent_id),
    action_id TEXT NOT NULL UNIQUE REFERENCES actions(action_id),
    sequence INTEGER NOT NULL, receipt_hash TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL, UNIQUE(agent_id, sequence)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL,
    agent_id TEXT, request_id TEXT, reason TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS actions_history ON actions(agent_id, created_at DESC);
CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
BEGIN SELECT RAISE(ABORT, 'Receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
BEGIN SELECT RAISE(ABORT, 'Receipts are append-only'); END;
"""
