"""Offline cryptographic verification; blockchain evidence requires a fresh RPC lookup."""

import argparse
import json
from pathlib import Path

from backend.receipts.verifier import verify_chain, verify_receipt_crypto

parser = argparse.ArgumentParser()
parser.add_argument("receipt", type=Path)
parser.add_argument("--public-key", required=True, help="Trusted PoA public key obtained out of band")
parser.add_argument("--chain", type=Path, help="JSON from /v1/receipts/{id}/chain")
args = parser.parse_args()
receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
hash_valid, signature_valid = verify_receipt_crypto(receipt, args.public_key)
chain_valid = None
if args.chain:
    chain = json.loads(args.chain.read_text(encoding="utf-8"))["items"]
    chain_valid = (
        verify_chain(chain, args.public_key, receipt["agent_id"])
        and chain[-1] == receipt
        and len(chain) == receipt["sequence"]
    )
print(
    json.dumps(
        {
            "hash_valid": hash_valid,
            "signature_valid": signature_valid,
            "chain_valid": chain_valid,
            "evidence_valid": None,
            "note": "Offline check does not verify the blockchain result.",
        },
        indent=2,
    )
)
raise SystemExit(0 if hash_valid and signature_valid and chain_valid is not False else 1)
