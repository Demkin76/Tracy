def migrate_control(conn):
    statements = [
        """CREATE TABLE IF NOT EXISTS control_policies(
            agent_id TEXT PRIMARY KEY REFERENCES agents(agent_id),version INTEGER NOT NULL,
            body TEXT NOT NULL,updated_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS control_policy_versions(
            agent_id TEXT NOT NULL REFERENCES agents(agent_id),version INTEGER NOT NULL,
            body TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(agent_id,version))""",
        """CREATE TABLE IF NOT EXISTS control_tasks(
            task_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL REFERENCES agents(agent_id),
            purpose TEXT NOT NULL,body TEXT NOT NULL,expires_at INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,created_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS control_intents(
            intent_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL REFERENCES agents(agent_id),
            request_id TEXT NOT NULL,task_id TEXT NOT NULL REFERENCES control_tasks(task_id),
            action TEXT NOT NULL,resource_id TEXT NOT NULL,request TEXT NOT NULL,intent_hash TEXT NOT NULL,
            policy TEXT NOT NULL,policy_version INTEGER NOT NULL,context TEXT NOT NULL,
            connector_hash TEXT NOT NULL,status TEXT NOT NULL,reason TEXT NOT NULL,
            target TEXT NOT NULL,units INTEGER NOT NULL,reserved_units INTEGER NOT NULL,
            asset TEXT NOT NULL,budget_day TEXT NOT NULL,created_at INTEGER NOT NULL,
            approval_expires_at INTEGER,approval TEXT,prepared TEXT,result TEXT,
            next_check_at INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
            receipt_id TEXT,UNIQUE(agent_id,request_id))""",
        """CREATE TABLE IF NOT EXISTS control_receipts(
            receipt_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL UNIQUE REFERENCES control_intents(intent_id),
            agent_id TEXT NOT NULL REFERENCES agents(agent_id),sequence INTEGER NOT NULL,
            receipt_hash TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(agent_id,sequence))""",
        """CREATE TABLE IF NOT EXISTS control_events(
            agent_id TEXT NOT NULL REFERENCES agents(agent_id),sequence INTEGER NOT NULL,
            event_hash TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(agent_id,sequence))""",
        "CREATE INDEX IF NOT EXISTS control_queue ON control_intents(status,next_check_at,created_at)",
    ]
    for statement in statements:
        conn.execute(statement)
    for table in ("control_receipts", "control_events", "control_policy_versions"):
        for action in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table}
                            BEGIN SELECT RAISE(ABORT,'Control evidence is append-only'); END;""")
    conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','5')")
