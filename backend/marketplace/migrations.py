def migrate_marketplace(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_offers(
        agent_id TEXT PRIMARY KEY REFERENCES agents(agent_id),
        kind TEXT NOT NULL, version INTEGER NOT NULL, enabled INTEGER NOT NULL,
        updated_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS installations(
        agent_id TEXT PRIMARY KEY REFERENCES agents(agent_id),
        owner_id TEXT NOT NULL REFERENCES users(user_id),
        source_agent_id TEXT NOT NULL REFERENCES agents(agent_id),
        source_name TEXT NOT NULL, kind TEXT NOT NULL, offer_version INTEGER NOT NULL,
        plan TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
        running INTEGER NOT NULL DEFAULT 0, next_run_at INTEGER,
        cycles INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
        install_request_id TEXT NOT NULL, install_hash TEXT NOT NULL,
        UNIQUE(owner_id,install_request_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS agent_runs(
        run_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES installations(agent_id),
        request_id TEXT NOT NULL, plan TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL, completed_at INTEGER,
        UNIQUE(agent_id,request_id))""")
    conn.execute("""CREATE INDEX IF NOT EXISTS agent_runs_queue ON agent_runs(status,created_at)""")
    conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','4')")
