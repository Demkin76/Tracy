"""Run one stable payout using a registered SDK agent."""

import argparse
import json
from pathlib import Path

from sdk.poa import PoAClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipient", required=True)
    parser.add_argument("--amount", type=float, default=0.01)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    keys = json.loads(args.key_file.read_text(encoding="utf-8"))
    with PoAClient(args.url) as client:
        print(
            json.dumps(
                client.payout(
                    keys["private_seed"], keys["agent_id"], args.recipient, args.amount, args.request_id
                ),
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
