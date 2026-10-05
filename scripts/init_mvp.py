"""Start a separate clean MVP database, retaining accounts and the original database."""

import argparse
import sqlite3
from pathlib import Path

from solders.keypair import Keypair

from backend.config import Settings
from backend.crypto.signatures import private_key, public_key
from backend.database.db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    args = parser.parse_args()
    settings = Settings()
    source = settings.database_path
    if args.target.exists() or not source.is_file():
        raise SystemExit("Source must exist and target must be new; no data was overwritten")
    with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as conn:
        users = conn.execute(
            "SELECT user_id,email,name,password_hash,created_at,recovery_hash FROM users"
        ).fetchall()
    db = Database(args.target)
    db.initialize(
        public_key(private_key(settings.signing_seed.get_secret_value())),
        str(
            Keypair.from_seed(
                private_key(settings.execution_wallet_seed.get_secret_value()).private_bytes_raw()
            ).pubkey()
        ),
    )
    with db.connect(write=True) as conn:
        conn.executemany(
            "INSERT INTO users(user_id,email,name,password_hash,created_at,recovery_hash) VALUES(?,?,?,?,?,?)",
            users,
        )
    print(
        f"Created {args.target} with {len(users)} accounts and no demo agents. Original {source} is preserved. Sessions require sign-in again."
    )


if __name__ == "__main__":
    main()
