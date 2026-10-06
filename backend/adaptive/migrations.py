def migrate_adaptive(conn):
    for sql in (
        """CREATE TABLE IF NOT EXISTS adaptive_strategies(
        strategy_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(user_id),
        body TEXT NOT NULL, strategy_hash TEXT NOT NULL, created_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS adaptive_agents(
        agent_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES users(user_id),
        strategy_id TEXT NOT NULL REFERENCES adaptive_strategies(strategy_id),name TEXT NOT NULL,
        revision INTEGER NOT NULL, source_bundle TEXT, created_at INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS adaptive_states(
        agent_id TEXT NOT NULL REFERENCES adaptive_agents(agent_id),revision INTEGER NOT NULL,
        body TEXT NOT NULL,state_hash TEXT NOT NULL,PRIMARY KEY(agent_id,revision))""",
        """CREATE TABLE IF NOT EXISTS adaptive_runs(
        run_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL REFERENCES adaptive_agents(agent_id),
        request_id TEXT NOT NULL,request_hash TEXT NOT NULL,body TEXT NOT NULL,report_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL,UNIQUE(agent_id,request_id))""",
        """CREATE TABLE IF NOT EXISTS adaptive_bundles(
        bundle_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES users(user_id),
        agent_id TEXT NOT NULL REFERENCES adaptive_agents(agent_id),revision INTEGER NOT NULL,
        body TEXT NOT NULL,bundle_hash TEXT NOT NULL,listed INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,UNIQUE(agent_id,revision))""",
        """CREATE TABLE IF NOT EXISTS adaptive_anchors(
        bundle_id TEXT PRIMARY KEY REFERENCES adaptive_bundles(bundle_id),
        signature TEXT NOT NULL,raw_tx TEXT NOT NULL,status TEXT NOT NULL,body TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS adaptive_forward(
        forward_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL REFERENCES adaptive_agents(agent_id),
        owner_id TEXT NOT NULL REFERENCES users(user_id),status TEXT NOT NULL,
        next_tick INTEGER NOT NULL,body TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS adaptive_forward_events(
        forward_id TEXT NOT NULL REFERENCES adaptive_forward(forward_id),sequence INTEGER NOT NULL,
        body TEXT NOT NULL,PRIMARY KEY(forward_id,sequence))""",
    ):
        conn.execute(sql)
    for table in ("adaptive_strategies", "adaptive_states", "adaptive_runs", "adaptive_forward_events"):
        for action in ("UPDATE", "DELETE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Adaptive evidence is immutable'); END"
            )
    conn.execute("""CREATE TRIGGER IF NOT EXISTS adaptive_bundle_immutable
        BEFORE UPDATE OF body,bundle_hash,owner_id,agent_id,revision,created_at ON adaptive_bundles
        BEGIN SELECT RAISE(ABORT,'Bundle snapshot is immutable'); END""")

    for sql in (
        "CREATE TABLE IF NOT EXISTS learning_decisions(decision_id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,owner_id TEXT NOT NULL,due_at INTEGER NOT NULL,body TEXT NOT NULL,decision_hash TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_jobs(decision_id TEXT PRIMARY KEY REFERENCES learning_decisions(decision_id),status TEXT NOT NULL,next_tick INTEGER NOT NULL,last_error TEXT)",
        "CREATE TABLE IF NOT EXISTS learning_outcomes(decision_id TEXT PRIMARY KEY REFERENCES learning_decisions(decision_id),agent_id TEXT NOT NULL,owner_id TEXT NOT NULL,body TEXT NOT NULL,outcome_hash TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS learning_changes(agent_id TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(agent_id,revision))",
        "CREATE TABLE IF NOT EXISTS learning_consumed(decision_id TEXT PRIMARY KEY REFERENCES learning_outcomes(decision_id),agent_id TEXT NOT NULL,revision INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS adaptive_reviews(agent_id TEXT NOT NULL,revision INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(agent_id,revision))",
        "CREATE INDEX IF NOT EXISTS learning_due ON learning_jobs(status,next_tick)",
    ):
        conn.execute(sql)
    for table in (
        "learning_decisions",
        "learning_outcomes",
        "learning_changes",
        "learning_consumed",
        "adaptive_reviews",
    ):
        for action in ("UPDATE", "DELETE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Learning evidence is immutable'); END"
            )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS bundle_prices(bundle_id TEXT PRIMARY KEY REFERENCES adaptive_bundles(bundle_id),body TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bundle_invoices(invoice_id TEXT PRIMARY KEY,bundle_id TEXT NOT NULL REFERENCES adaptive_bundles(bundle_id),owner_id TEXT NOT NULL REFERENCES users(user_id),body TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bundle_payment_receipts(invoice_id TEXT PRIMARY KEY REFERENCES bundle_invoices(invoice_id),signature TEXT UNIQUE NOT NULL,body TEXT NOT NULL)"
    )
    for table in ("bundle_invoices", "bundle_payment_receipts"):
        for action in ("UPDATE", "DELETE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Payment evidence is immutable'); END"
            )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS devnet_swaps(swap_id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES users(user_id),body TEXT NOT NULL,receipt TEXT)"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS devnet_swap_immutable BEFORE UPDATE OF body,owner_id ON devnet_swaps BEGIN SELECT RAISE(ABORT,'Swap quote is immutable'); END"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS devnet_swap_receipt_immutable BEFORE UPDATE OF receipt ON devnet_swaps WHEN OLD.receipt IS NOT NULL BEGIN SELECT RAISE(ABORT,'Swap receipt is immutable'); END"
    )
