"""Opt-in real Devnet smoke test. Uses only test SOL and stores evidence in data/."""

import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from solders.keypair import Keypair

from backend.blockchain.solana import SolanaGateway
from backend.config import Settings
from sdk.poa import PoAClient, generate_keypair


async def run(airdrop: bool):
    settings = Settings()
    gateway = SolanaGateway(settings)
    try:
        health = await gateway.health()
        print(json.dumps({"wallet": gateway.sender, **health}))
        if health["balance_lamports"] < 20_000_000:
            if not airdrop:
                raise SystemExit(
                    "Insufficient Devnet funds; fund the wallet or pass --airdrop for one faucet request."
                )
            try:
                response = await gateway.submit_rpc.request_airdrop(gateway.wallet.pubkey(), 1_000_000_000)
                print("Airdrop transaction:", response.value)
            except Exception as exc:
                raise SystemExit(
                    f"Devnet faucet unavailable: {type(exc).__name__}. Fund the displayed wallet at https://faucet.solana.com/ ."
                ) from exc
            for _ in range(12):
                await asyncio.sleep(2)
                if (await gateway.health())["balance_lamports"] >= 20_000_000:
                    break
            else:
                raise SystemExit("Airdrop not confirmed yet. No transfer submitted.")
    finally:
        await gateway.close()
    keys, recipient = generate_keypair(), str(Keypair().pubkey())
    agent_id = "smoke_" + uuid4().hex[:16]
    root = Path("data")
    root.mkdir(exist_ok=True)
    (root / "smoke-agent.json").write_text(json.dumps({**keys, "agent_id": agent_id}), encoding="utf-8")
    with PoAClient() as client:
        client.register(
            agent_id,
            "Devnet smoke test",
            keys["public_key"],
            {
                "allowed_actions": ["solana.transfer"],
                "max_transfer_sol": 0.1,
                "daily_budget_sol": 1.0,
                "allowed_recipients": [recipient],
            },
        )
        result = client.transfer(keys["private_seed"], agent_id, recipient, 0.01)
        for _ in range(12):
            if result["receipt_id"]:
                break
            time.sleep(2)
            result = client.reconcile(result["action_id"])
        evidence = {"transfer": result}
        if result["receipt_id"]:
            evidence["verification"] = client.verify(result["receipt_id"])
        evidence["rejection"] = client.transfer(keys["private_seed"], agent_id, recipient, 5)
        (root / "live-smoke-result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "receipt_id": result["receipt_id"],
                    "tx_signature": result["tx_signature"],
                    "verification": evidence.get("verification"),
                    "rejection_status": evidence["rejection"]["status"],
                },
                indent=2,
            )
        )
        if result["status"] != "VERIFIED" or not evidence.get("verification", {}).get("valid"):
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--airdrop", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.airdrop))
