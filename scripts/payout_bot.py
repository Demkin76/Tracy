"""A standalone bot: stable job IDs survive process restarts without another transfer."""

import argparse
import json
import os
from pathlib import Path

from sdk.poa import PoAClient


def main():
    parser = argparse.ArgumentParser(description="Tracy example payout bot")
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--url", default=os.environ.get("TRACY_URL", "http://127.0.0.1:8000"))
    args = parser.parse_args()
    if not os.environ.get("TRACY_API_KEY"):
        parser.error("Set TRACY_API_KEY before starting the bot")
    keys = json.loads(args.key_file.read_text(encoding="utf-8"))
    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    if not isinstance(jobs, list) or len({j["request_id"] for j in jobs}) != len(jobs):
        parser.error("Jobs must be a list with unique, stable request_id values")
    with PoAClient(args.url) as tracy:
        for job in jobs:
            result = tracy.payout(
                keys["private_seed"], keys["agent_id"], job["to"], job["amount"], job["request_id"]
            )
            print(json.dumps({k: result[k] for k in ("action_id", "status", "reason", "receipt_id")}))
            if result["receipt_id"]:
                print(json.dumps({"verification": tracy.verify(result["receipt_id"])}))


if __name__ == "__main__":
    main()
