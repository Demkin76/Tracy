def migrate_platform(conn):
    changes = {
        "agents": {
            "listed": "INTEGER NOT NULL DEFAULT 0",
            "category": "TEXT NOT NULL DEFAULT 'payouts'",
            "tagline": "TEXT NOT NULL DEFAULT ''",
            "published_at": "INTEGER",
            "status_version": "INTEGER NOT NULL DEFAULT 1",
        },
        "actions": {
            "next_check_at": "INTEGER NOT NULL DEFAULT 0",
            "check_attempts": "INTEGER NOT NULL DEFAULT 0",
            "last_checked_at": "INTEGER",
            "completed_at": "INTEGER",
        },
        "users": {"recovery_hash": "TEXT"},
        "api_keys": {"scope": "TEXT NOT NULL DEFAULT 'manage'", "last_used_at": "INTEGER"},
    }
    for table, columns in changes.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    for sql in [
        """CREATE TABLE IF NOT EXISTS proof_shares(
            share_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(user_id),
            receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id), created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL, revoked_at INTEGER)""",
        """CREATE TABLE IF NOT EXISTS favorites(
            user_id TEXT NOT NULL REFERENCES users(user_id), agent_id TEXT NOT NULL REFERENCES agents(agent_id),
            created_at INTEGER NOT NULL, PRIMARY KEY(user_id,agent_id))""",
        """CREATE TABLE IF NOT EXISTS account_events(
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(user_id),
            kind TEXT NOT NULL, target TEXT NOT NULL, created_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS notification_reads(
            user_id TEXT NOT NULL REFERENCES users(user_id), receipt_id TEXT NOT NULL REFERENCES receipts(receipt_id),
            PRIMARY KEY(user_id,receipt_id))""",
        "CREATE INDEX IF NOT EXISTS actions_pending_check ON actions(status,next_check_at)",
        "CREATE INDEX IF NOT EXISTS agents_catalog ON agents(listed,category)",
        "CREATE INDEX IF NOT EXISTS events_owner ON account_events(user_id,event_id)",
    ]:
        conn.execute(sql)
    conn.execute("""UPDATE actions SET completed_at=(SELECT json_extract(body,'$.timestamp') FROM receipts r
                  WHERE r.action_id=actions.action_id) WHERE completed_at IS NULL AND receipt_id IS NOT NULL""")
    conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','3')")
