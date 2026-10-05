import argparse
import json
from pathlib import Path

from backend.trading.verify import verify_chain


def main():
    p = argparse.ArgumentParser()
    p.add_argument("bundle", type=Path)
    p.add_argument("--public-key", required=True)
    args = p.parse_args()
    value = json.loads(args.bundle.read_text(encoding="utf-8"))
    chain = value.get("chain", value.get("receipts", []))
    valid = bool(chain) and verify_chain(chain, args.public_key)
    print(
        json.dumps(
            {
                "valid": valid,
                "mode": "paper",
                "on_chain": False,
                "note": "Offline signatures and chain only. Fresh ledger readback is a separate check.",
            }
        )
    )
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
