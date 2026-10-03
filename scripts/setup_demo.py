"""Create local keys. Does not request SOL or send transfers."""

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from solders.keypair import Keypair

from backend.crypto.signatures import encode_base64, public_key


def main():
    path = Path(".env")
    if path.exists():
        raise SystemExit(".env already exists; preserving existing identities and keys.")
    poa, wallet = Ed25519PrivateKey.generate(), Keypair()
    path.write_text(
        f"POA_SIGNING_SEED={encode_base64(poa.private_bytes_raw())}\n"
        f"POA_EXECUTION_WALLET_SEED={encode_base64(bytes(wallet)[:32])}\n"
        "POA_RPC_URL=https://api.devnet.solana.com\n"
        "POA_VERIFICATION_RPC_URL=https://api.devnet.solana.com\n"
        "POA_DATABASE_PATH=data/poa.sqlite3\n",
        encoding="utf-8",
    )
    print("Created .env. Keep it private and back it up with the database.")
    print("Execution wallet (Devnet only):", wallet.pubkey())
    print("PoA public key (pin in independent verifiers):", public_key(poa))
    print("Fund the execution wallet with test SOL at https://faucet.solana.com/ .")
    print("Open Tracy and create an account, or run python -m scripts.bootstrap_owner for the local demo.")


if __name__ == "__main__":
    main()
