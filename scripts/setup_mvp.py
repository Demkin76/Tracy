"""Create a fresh paper MVP configuration; never seed sample agents or overwrite keys."""

import argparse
import base64
import json
import os
import re
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", help="Public hostname; creates .env.production for HTTPS deployment")
    args = parser.parse_args()
    domain = args.domain
    if domain and not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", domain):
        parser.error("Provide a hostname without scheme, port or path")
    path = Path(".env.production" if domain else ".env")
    values = {
        "POA_SIGNING_SEED": base64.b64encode(secrets.token_bytes(32)).decode(),
        "POA_EXECUTION_WALLET_SEED": base64.b64encode(secrets.token_bytes(32)).decode(),
        "POA_DATABASE_PATH": "data/tracy-mvp.sqlite3",
        "POA_DEVNET_ENABLED": "false",
        "POA_CONTROL_RESOURCES_PATH": "data/mvp-resources.json",
        "POA_CONTROL_CREDENTIALS_PATH": "data/mvp-credentials.json",
        "POA_ENVIRONMENT": "production" if domain else "development",
        "POA_COOKIE_SECURE": "true" if domain else "false",
        "POA_SIGNUP_ENABLED": "false" if domain else "true",
        "POA_ALLOWED_HOSTS": json.dumps([domain, "127.0.0.1"] if domain else ["localhost", "127.0.0.1"]),
        "POA_CORS_ORIGINS": json.dumps(
            ["https://" + domain] if domain else ["http://localhost:5173", "http://127.0.0.1:5173"]
        ),
    }
    if domain:
        values["TRACY_DOMAIN"] = domain
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(f"{path} already exists. Existing keys and settings were preserved.") from None
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print(f"Created {path} with fresh private signing keys. Back it up securely with the database.")
    print("No agents, balances, credentials or trading results were seeded.")


if __name__ == "__main__":
    main()
