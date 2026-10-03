"""Verify an exported receipt and audit bundle against a separately trusted key."""

import argparse
import json
from pathlib import Path

from backend.control.verify import verify_bundle, verify_events


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--public-key", required=True)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    receipts = verify_bundle(bundle["receipts"], args.public_key)
    events = verify_events(bundle["items"], args.public_key)
    print(
        json.dumps(
            {
                "receipts": receipts,
                "audit_chain_valid": events,
                "external_result": "Requires fresh connector readback; signatures alone do not prove external state.",
            }
        )
    )
    raise SystemExit(0 if receipts["valid"] and events else 1)


if __name__ == "__main__":
    main()
