def migrate_strategies(conn):
    statements = [
        """CREATE TABLE IF NOT EXISTS strategies(
        strategy_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(user_id),
        agent_id TEXT NOT NULL REFERENCES agents(agent_id), name TEXT NOT NULL, description TEXT NOT NULL,
        version INTEGER NOT NULL,status TEXT NOT NULL,listed INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS strategy_versions(
        strategy_id TEXT NOT NULL REFERENCES strategies(strategy_id),version INTEGER NOT NULL,
        body TEXT NOT NULL,created_at INTEGER NOT NULL,PRIMARY KEY(strategy_id,version))""",
        """CREATE TABLE IF NOT EXISTS strategy_tests(
        test_id TEXT PRIMARY KEY,strategy_id TEXT NOT NULL REFERENCES strategies(strategy_id),
        strategy_version INTEGER NOT NULL,started_at INTEGER NOT NULL,finished_at INTEGER NOT NULL,
        body TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS trading_deployments(
        deployment_id TEXT PRIMARY KEY,strategy_id TEXT NOT NULL REFERENCES strategies(strategy_id),
        strategy_version INTEGER NOT NULL,status TEXT NOT NULL,step INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,baseline_test_id TEXT NOT NULL REFERENCES strategy_tests(test_id),
        runner_seed TEXT NOT NULL,runner_public_key TEXT NOT NULL,UNIQUE(strategy_id,strategy_version))""",
        """CREATE TABLE IF NOT EXISTS trading_intents(
        intent_id TEXT PRIMARY KEY,deployment_id TEXT NOT NULL REFERENCES trading_deployments(deployment_id),
        agent_id TEXT NOT NULL,request_id TEXT NOT NULL,intent_hash TEXT NOT NULL,
        request TEXT NOT NULL,decision TEXT NOT NULL,policy TEXT NOT NULL,
        status TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL,
        approval_expires_at INTEGER NOT NULL,approval TEXT,UNIQUE(agent_id,request_id))""",
        """CREATE TABLE IF NOT EXISTS paper_fills(
        trade_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL UNIQUE REFERENCES trading_intents(intent_id),
        deployment_id TEXT NOT NULL REFERENCES trading_deployments(deployment_id),body TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS trading_marks(
        deployment_id TEXT NOT NULL,step INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(deployment_id,step))""",
        """CREATE TABLE IF NOT EXISTS trading_receipts(
        trade_id TEXT PRIMARY KEY REFERENCES paper_fills(trade_id),strategy_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,receipt_hash TEXT NOT NULL,body TEXT NOT NULL,UNIQUE(strategy_id,sequence))""",
        """CREATE TABLE IF NOT EXISTS degradation_alerts(
        alert_id TEXT PRIMARY KEY,strategy_id TEXT NOT NULL,version INTEGER NOT NULL,
        kind TEXT NOT NULL,severity TEXT NOT NULL,message TEXT NOT NULL,created_at INTEGER NOT NULL,
        acknowledged INTEGER NOT NULL DEFAULT 0,UNIQUE(strategy_id,version,kind,message))""",
        "CREATE INDEX IF NOT EXISTS strategy_owner ON strategies(owner_id,updated_at)",
        "CREATE INDEX IF NOT EXISTS trade_deployment ON paper_fills(deployment_id)",
    ]
    for sql in statements:
        conn.execute(sql)
    for table in ("strategy_versions", "strategy_tests", "paper_fills", "trading_receipts", "trading_marks"):
        for action in ("UPDATE", "DELETE"):
            conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()}
            BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Trading evidence is append-only'); END""")
    conn.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','6')")
