"""Consistent online SQLite backup. Never overwrites an existing backup."""

import argparse
import json
import sqlite3
from pathlib import Path

from backend.config import Settings
from backend.receipts.verifier import verify_receipt_crypto


def validate(path):
    with sqlite3.connect(path) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        key = conn.execute("SELECT value FROM metadata WHERE key='poa_public_key'").fetchone()[0]
        count = 0
        for (body,) in conn.execute("SELECT body FROM receipts"):
            if not all(verify_receipt_crypto(json.loads(body), key)):
                raise ValueError("Invalid signed receipt in backup")
            count += 1
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "control_receipts" in tables:
            from backend.control.verify import verify_bundle, verify_events

            ids = [r[0] for r in conn.execute("SELECT DISTINCT agent_id FROM control_receipts")]
            for agent_id in ids:
                chain = [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM control_receipts WHERE agent_id=? ORDER BY sequence", (agent_id,)
                    )
                ]
                if not verify_bundle(chain, key)["valid"]:
                    raise ValueError("Invalid control receipt chain")
                count += len(chain)
            for (agent_id,) in conn.execute("SELECT DISTINCT agent_id FROM control_events"):
                events = [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM control_events WHERE agent_id=? ORDER BY sequence", (agent_id,)
                    )
                ]
                if not verify_events(events, key):
                    raise ValueError("Invalid control audit chain")
        if "trading_receipts" in tables:
            from backend.trading.verify import verify_chain

            for (strategy_id,) in conn.execute("SELECT DISTINCT strategy_id FROM trading_receipts"):
                chain = [
                    json.loads(r[0])
                    for r in conn.execute(
                        "SELECT body FROM trading_receipts WHERE strategy_id=? ORDER BY sequence",
                        (strategy_id,),
                    )
                ]
                if not verify_chain(chain, key):
                    raise ValueError("Invalid trading receipt chain")
                for receipt in chain:
                    fill = conn.execute(
                        "SELECT body FROM paper_fills WHERE trade_id=?", (receipt["trade_id"],)
                    ).fetchone()
                    if not fill or json.loads(fill[0]) != receipt["trade"]:
                        raise ValueError("Trading proof does not match the paper ledger")
                count += len(chain)
        return count


def backup(source, target):
    if not source.is_file():
        raise ValueError("Source database does not exist")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Reserve destination exclusively. Never overwrite the running database or another backup.
    with target.open("xb"):
        pass
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    return validate(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--source", type=Path, help="For restore testing, specify a saved backup as the source"
    )
    args = parser.parse_args()
    source = args.source or Settings().database_path
    count = backup(source, args.out)
    print(
        json.dumps(
            {
                "backup": str(args.out.resolve()),
                "verified_receipts": count,
                "note": "Preserve the matching .env signing/execution seeds separately.",
            }
        )
    )


if __name__ == "__main__":
    main()
