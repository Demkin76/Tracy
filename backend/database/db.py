import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from backend.control.migrations import migrate_control
from backend.database.migrations import migrate
from backend.database.models import SCHEMA
from backend.marketplace.migrations import migrate_marketplace
from backend.platform.migrations import migrate_platform


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self, signing_public_key: str, execution_wallet: str):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
        with self.connect(write=True) as conn:
            migrate(conn)
            migrate_platform(conn)
            migrate_marketplace(conn)
            migrate_control(conn)
            for key, value in {
                "poa_public_key": signing_public_key,
                "execution_wallet": execution_wallet,
            }.items():
                existing = conn.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
                if existing and existing["value"] != value:
                    raise RuntimeError(f"{key} differs from the database identity; restore the original .env")
                conn.execute("INSERT OR IGNORE INTO metadata VALUES (?, ?)", (key, value))

    def audit(self, reason, agent_id=None, request_id=None):
        with self.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO audit_events(timestamp,agent_id,request_id,reason) VALUES(?,?,?,?)",
                (int(time.time()), agent_id, request_id, reason),
            )

    def action(self, action_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM actions WHERE action_id=?", (action_id,)).fetchone()
        return unpack_action(row) if row else None

    def update_action(self, action_id, **fields):
        allowed = {"status", "reason", "tx_signature"}
        if not fields or not fields.keys() <= allowed:
            raise ValueError("Invalid action update")
        with self.connect(write=True) as conn:
            conn.execute(
                f"UPDATE actions SET {','.join(f'{key}=?' for key in fields)} WHERE action_id=? AND receipt_id IS NULL",
                (*fields.values(), action_id),
            )


def unpack_action(row) -> dict:
    result = dict(row)
    for key in ("request", "policy", "decision_context"):
        result[key] = json.loads(result[key])
    return result
