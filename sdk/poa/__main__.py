import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from sdk.poa import PoAClient
from sdk.poa.signing import generate_keypair


def save_new(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental key loss on reruns.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(content, handle, indent=2)
    if os.name != "nt":
        path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description="Tracy Python SDK · Solana Devnet")
    parser.add_argument("--url", default=os.environ.get("TRACY_URL", "http://127.0.0.1:8000"))
    commands = parser.add_subparsers(dest="command", required=True)
    keygen = commands.add_parser("keygen")
    init = commands.add_parser("init")
    transfer = commands.add_parser("transfer")
    for sub in (keygen, init, transfer):
        sub.add_argument("--key-file", type=Path, required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--description", default="Persistent Python SDK agent")
    init.add_argument("--recipient", action="append", required=True)
    init.add_argument("--limit", type=float, default=0.1)
    init.add_argument("--daily-budget", type=float, default=1.0)
    transfer.add_argument("--to", required=True)
    transfer.add_argument("--amount", type=float, required=True)
    transfer.add_argument("--request-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "keygen":
            keys = {**generate_keypair(), "agent_id": "agent_" + uuid4().hex}
            save_new(args.key_file, keys)
            print(
                json.dumps(
                    {
                        "agent_id": keys["agent_id"],
                        "public_key": keys["public_key"],
                        "key_file": str(args.key_file.resolve()),
                    },
                    indent=2,
                )
            )
            return
        if not os.environ.get("TRACY_API_KEY"):
            parser.error("Set TRACY_API_KEY to a personal API key from Connect SDK.")
        with PoAClient(args.url) as tracy:
            if args.command == "init":
                if not args.key_file.exists():
                    save_new(args.key_file, {**generate_keypair(), "agent_id": "agent_" + uuid4().hex})
                keys = json.loads(args.key_file.read_text(encoding="utf-8"))
                try:
                    result = tracy.agent(keys["agent_id"])
                    if result["public_key"] != keys["public_key"]:
                        raise ValueError("Registered public key does not match the local key file")
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        raise
                    result = tracy.register(
                        keys["agent_id"],
                        args.name,
                        keys["public_key"],
                        {
                            "max_transfer_sol": args.limit,
                            "daily_budget_sol": args.daily_budget,
                            "allowed_recipients": args.recipient,
                            "allowed_actions": ["solana.transfer"],
                        },
                        args.description,
                    )
                print(json.dumps(result, indent=2))
            else:
                keys = json.loads(args.key_file.read_text(encoding="utf-8"))
                result = tracy.payout(
                    keys["private_seed"], keys["agent_id"], args.to, args.amount, args.request_id
                )
                print(json.dumps(result, indent=2))
    except httpx.HTTPStatusError as exc:
        parser.exit(1, f"Tracy HTTP {exc.response.status_code}: {exc.response.text}\n")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
