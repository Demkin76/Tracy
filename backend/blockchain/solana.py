import json
from dataclasses import dataclass

from solana.rpc.async_api import AsyncClient
from solana.rpc.core import RPCException
from solana.rpc.models import TxOpts
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.rpc.errors import SendTransactionPreflightFailureMessage
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from backend.config import Settings
from backend.crypto.signatures import decode_base64

DEVNET_GENESIS_HASH = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"
SYSTEM_PROGRAM = "11111111111111111111111111111111"
MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


class PreflightRejected(Exception):
    pass


@dataclass
class PreparedTransfer:
    raw: bytes
    signature: str


@dataclass
class Evidence:
    status: str  # verified, mismatch, failed, pending, unavailable
    reason: str
    slot: int | None = None

    def to_dict(self):
        return {"status": self.status, "reason": self.reason, "slot": self.slot, "commitment": "confirmed"}


def inspect_transaction(
    tx: dict | None, signature: str, sender: str, recipient: str, lamports: int, request_hash: str
) -> Evidence:
    """Verify the exact one-instruction native transfer, including balance effects."""
    if tx is None:
        return Evidence("pending", "transaction_not_confirmed")
    try:
        slot = tx["slot"]
        meta = tx["meta"]
        transaction = tx["transaction"]
        if transaction["signatures"] != [signature]:
            return Evidence("mismatch", "transaction_signature_mismatch", slot)
        if not meta or "err" not in meta:
            return Evidence("unavailable", "transaction_metadata_unavailable", slot)
        if meta["err"] is not None:
            return Evidence("failed", "transaction_failed_on_chain", slot)
        message = transaction["message"]
        instructions = message["instructions"]
        if len(instructions) != 2 or meta.get("innerInstructions"):
            return Evidence("mismatch", "unexpected_instructions", slot)
        memo = instructions[1]
        if memo.get("programId") != MEMO_PROGRAM or memo.get("parsed") != "poa:" + request_hash:
            return Evidence("mismatch", "request_binding_mismatch", slot)
        instruction = instructions[0]
        parsed = instruction.get("parsed", {})
        expected = {"source": sender, "destination": recipient, "lamports": lamports}
        if (
            instruction.get("programId") != SYSTEM_PROGRAM
            or parsed.get("type") != "transfer"
            or parsed.get("info") != expected
        ):
            return Evidence("mismatch", "transfer_fields_mismatch", slot)
        keys = message["accountKeys"]
        addresses = [key["pubkey"] for key in keys]
        if (
            keys[0]["pubkey"] != sender
            or not keys[0]["signer"]
            or not keys[0]["writable"]
            or sender == recipient
            or sum(bool(key["signer"]) for key in keys) != 1
        ):
            return Evidence("mismatch", "sender_mismatch", slot)
        source_index, dest_index = addresses.index(sender), addresses.index(recipient)
        if not keys[dest_index]["writable"]:
            return Evidence("mismatch", "recipient_not_writable", slot)
        before, after = meta["preBalances"], meta["postBalances"]
        if (
            after[dest_index] - before[dest_index] != lamports
            or before[source_index] - after[source_index] != lamports + meta["fee"]
        ):
            return Evidence("mismatch", "balance_changes_mismatch", slot)
        return Evidence("verified", "exact_transfer_confirmed", slot)
    except (KeyError, IndexError, TypeError, ValueError):
        return Evidence("unavailable", "malformed_rpc_evidence")


class SolanaGateway:
    def __init__(self, settings: Settings):
        self.wallet = Keypair.from_seed(decode_base64(settings.execution_wallet_seed.get_secret_value(), 32))
        self.sender = str(self.wallet.pubkey())
        self.submit_rpc = AsyncClient(settings.rpc_url, timeout=15, commitment="confirmed")
        self.verify_rpc = AsyncClient(settings.verification_rpc_url, timeout=15, commitment="confirmed")

    async def close(self):
        await self.submit_rpc.close()
        await self.verify_rpc.close()

    async def ensure_devnet(self, client):
        if str((await client.get_genesis_hash()).value) != DEVNET_GENESIS_HASH:
            raise RuntimeError("RPC endpoint is not Solana Devnet")

    async def prepare(self, recipient: str, lamports: int, request_hash: str) -> PreparedTransfer:
        # Both independently configured clients must identify as Devnet before any spending.
        await self.ensure_devnet(self.submit_rpc)
        await self.ensure_devnet(self.verify_rpc)
        blockhash = (await self.submit_rpc.get_latest_blockhash()).value.blockhash
        instruction = transfer(
            TransferParams(
                from_pubkey=self.wallet.pubkey(), to_pubkey=Pubkey.from_string(recipient), lamports=lamports
            )
        )
        memo = Instruction(Pubkey.from_string(MEMO_PROGRAM), ("poa:" + request_hash).encode("ascii"), [])
        tx = Transaction.new_signed_with_payer(
            [instruction, memo], self.wallet.pubkey(), [self.wallet], blockhash
        )
        return PreparedTransfer(bytes(tx), str(tx.signatures[0]))

    async def broadcast(self, prepared: PreparedTransfer):
        try:
            response = await self.submit_rpc.send_raw_transaction(
                prepared.raw,
                opts=TxOpts(skip_confirmation=True, skip_preflight=False, preflight_commitment="confirmed"),
            )
        except RPCException as exc:
            if exc.args and isinstance(exc.args[0], SendTransactionPreflightFailureMessage):
                raise PreflightRejected("Transaction rejected before broadcast") from exc
            raise
        if str(response.value) != prepared.signature:
            raise RuntimeError("RPC returned an unexpected transaction signature")

    async def verify_transfer(
        self, signature: str, sender: str, recipient: str, lamports: int, request_hash: str
    ) -> Evidence:
        try:
            await self.ensure_devnet(self.verify_rpc)
            response = await self.verify_rpc.get_transaction(
                Signature.from_string(signature),
                encoding="jsonParsed",
                commitment="confirmed",
                max_supported_transaction_version=0,
            )
            # Inspect RPC data, never the transaction object constructed for submission.
            tx = json.loads(response.to_json())["result"]
            return inspect_transaction(tx, signature, sender, recipient, lamports, request_hash)
        except Exception:
            return Evidence("unavailable", "rpc_unavailable_or_wrong_network")

    async def health(self):
        await self.ensure_devnet(self.submit_rpc)
        await self.ensure_devnet(self.verify_rpc)
        balance = (await self.submit_rpc.get_balance(self.wallet.pubkey())).value
        return {"rpc_available": True, "balance_lamports": balance}
