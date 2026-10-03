"""One-time local migration of unowned MVP agents into the local Tracy owner account."""

import json
import secrets
from pathlib import Path

from solders.keypair import Keypair

from backend.auth.models import Signup
from backend.auth.service import AuthService
from backend.config import Settings
from backend.crypto.signatures import private_key, public_key
from backend.database.db import Database


def main():
    settings = Settings()
    db = Database(settings.database_path)
    signing = private_key(settings.signing_seed.get_secret_value())
    wallet_seed = private_key(settings.execution_wallet_seed.get_secret_value()).private_bytes_raw()
    db.initialize(public_key(signing), str(Keypair.from_seed(wallet_seed).pubkey()))
    auth = AuthService(db, settings)
    path = Path("data/tracy-owner.json")
    if path.exists():
        credentials = json.loads(path.read_text(encoding="utf-8"))
        user = auth.get(credentials["user_id"])
        if user["email"] != credentials["email"]:
            raise RuntimeError("Owner file does not match the database")
    else:
        credentials = {
            "email": "owner@tracy.local",
            "password": secrets.token_urlsafe(24),
            "name": "Tracy owner",
        }
        user = auth.register(Signup(**credentials))
        credentials["user_id"] = user["user_id"]
        with path.open("x", encoding="utf-8") as handle:
            json.dump(credentials, handle, indent=2)
    with db.connect(write=True) as conn:
        count = conn.execute(
            "UPDATE agents SET owner_id=? WHERE owner_id IS NULL", (user["user_id"],)
        ).rowcount
    print(
        json.dumps(
            {
                "owner_email": user["email"],
                "credentials_file": str(path.resolve()),
                "legacy_agents_assigned": count,
            }
        )
    )


if __name__ == "__main__":
    main()
