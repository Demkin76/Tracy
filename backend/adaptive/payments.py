"""Non-custodial test-SOL licenses. Exact split settles atomically on Devnet."""

import base64
import json
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, field_validator
from solders.instruction import Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

from backend.actions.models import StrictModel
from backend.blockchain.solana import MEMO_PROGRAM, SYSTEM_PROGRAM
from backend.execution_control import require_execution


class Price(StrictModel):
    lamports: int = Field(ge=0, le=1_000_000, strict=True)
    creator_wallet: str

    @field_validator("lamports")
    @classmethod
    def valid_price(cls, v):
        if 0 < v < 100:
            raise ValueError("Paid licenses require at least 100 lamports")
        return v

    @field_validator("creator_wallet")
    @classmethod
    def address(cls, v):
        key = Pubkey.from_string(v)
        if not key.is_on_curve():
            raise ValueError("Use a signing wallet address")
        return str(key)


class Checkout(StrictModel):
    payer: str

    @field_validator("payer")
    @classmethod
    def address(cls, v):
        return Price.address(v)


class SignedTransaction(StrictModel):
    transaction: str = Field(min_length=1, max_length=5000)


class Confirm(StrictModel):
    signature: str = Field(min_length=64, max_length=100)

    @field_validator("signature")
    @classmethod
    def sig(cls, v):
        return str(Signature.from_string(v))


def inspect_payment(tx, signature, invoice):
    try:
        message = tx["transaction"]["message"]
        meta = tx["meta"]
        signers = [k["pubkey"] for k in message["accountKeys"] if k["signer"]]
        instructions = message["instructions"]
        expected = [
            (invoice["creator_wallet"], invoice["creator_lamports"]),
            (invoice["platform_wallet"], invoice["platform_lamports"]),
        ]
        expected = [x for x in expected if x[1] > 0]
        if (
            meta["err"] is not None
            or tx["transaction"]["signatures"] != [signature]
            or signers != [invoice["payer"]]
            or len(instructions) != len(expected) + 1
            or not invoice["created_at"] - 30 <= tx["blockTime"] <= invoice["expires_at"] + 30
        ):
            return False
        for ix, (recipient, amount) in zip(instructions, expected):
            if ix.get("programId") != SYSTEM_PROGRAM or ix["parsed"]["type"] != "transfer":
                return False
            info = ix["parsed"]["info"]
            if (info["source"], info["destination"], info["lamports"]) != (
                invoice["payer"],
                recipient,
                amount,
            ):
                return False
        memo = instructions[-1]
        return (
            memo.get("programId") == MEMO_PROGRAM
            and memo.get("parsed") == "tracy-license:" + invoice["invoice_id"]
        )
    except (KeyError, TypeError, ValueError):
        return False


class Payments:
    def __init__(self, adaptive, gateway):
        self.a, self.db, self.gateway = adaptive, adaptive.db, gateway

    def enabled(self):
        if not self.a.s.settings.adaptive_devnet_payments_enabled:
            raise HTTPException(409, "Test-SOL payments are disabled on this deployment")
        require_execution(self.a.s.settings)

    def pricing(self, bid):
        self.a.get_bundle(bid)
        with self.db.connect() as conn:
            row = conn.execute("SELECT body FROM bundle_prices WHERE bundle_id=?", (bid,)).fetchone()
        return (
            self.a.checked(json.loads(row[0]))
            if row
            else {"lamports": 0, "network": "solana-devnet", "fee_bps": 500}
        )

    def set_price(self, bid, uid, payload):
        self.enabled()
        with self.db.connect(write=True) as conn:
            if not conn.execute(
                "SELECT 1 FROM adaptive_bundles WHERE bundle_id=? AND owner_id=?", (bid, uid)
            ).fetchone():
                raise HTTPException(404, "Bundle not found")
            if payload.lamports and payload.creator_wallet == self.gateway.sender:
                raise HTTPException(422, "Creator payout wallet must differ from platform wallet")
            body = payload.model_dump() | {
                "network": "solana-devnet",
                "fee_bps": 500,
                "platform_wallet": self.gateway.sender,
                "updated_at": int(time.time()),
            }
            conn.execute(
                "INSERT INTO bundle_prices VALUES(?,?) ON CONFLICT(bundle_id) DO UPDATE SET body=excluded.body",
                (bid, json.dumps(self.a.signed(body))),
            )
        return body

    def require_license(self, bid, uid):
        with self.db.connect() as conn:
            own = conn.execute("SELECT owner_id FROM adaptive_bundles WHERE bundle_id=?", (bid,)).fetchone()
            price = conn.execute("SELECT body FROM bundle_prices WHERE bundle_id=?", (bid,)).fetchone()
            if not price or (own and own[0] == uid):
                return
            value = self.a.checked(json.loads(price[0]))
            if not value["lamports"]:
                return
            paid = conn.execute(
                "SELECT r.body FROM bundle_payment_receipts r JOIN bundle_invoices i ON i.invoice_id=r.invoice_id WHERE i.bundle_id=? AND i.owner_id=?",
                (bid, uid),
            ).fetchone()
            if not paid:
                raise HTTPException(
                    402, "A verified test-SOL license is required to create this Bundle instance"
                )
            self.a.checked(json.loads(paid[0]))

    async def checkout(self, bid, uid, payload):
        self.enabled()
        price = self.pricing(bid)
        if price["lamports"] < 100:
            raise HTTPException(409, "This Bundle is free; create an instance directly")
        if payload.payer in (price["creator_wallet"], price["platform_wallet"]):
            raise HTTPException(422, "Payer must differ from payout wallets")
        now = int(time.time())
        iid = "invoice_" + uuid4().hex
        fee = price["lamports"] * price["fee_bps"] // 10000
        body = price | {
            "invoice_id": iid,
            "bundle_id": bid,
            "payer": payload.payer,
            "created_at": now,
            "expires_at": now + 600,
            "creator_lamports": price["lamports"] - fee,
            "platform_lamports": fee,
            "meaning": "Test-SOL access license; public strategy evidence remains downloadable. Network fee is additional.",
        }
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO bundle_invoices VALUES(?,?,?,?)",
                (iid, bid, uid, json.dumps(self.a.signed(body))),
            )
        return self.invoice(iid, uid)

    def invoice(self, iid, uid):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT body FROM bundle_invoices WHERE invoice_id=? AND owner_id=?", (iid, uid)
            ).fetchone()
            receipt = conn.execute(
                "SELECT body FROM bundle_payment_receipts WHERE invoice_id=?", (iid,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Invoice not found")
        envelope = json.loads(row[0])
        self.a.checked(envelope)
        if receipt:
            self.a.checked(json.loads(receipt[0]))
        return {"invoice": envelope, "receipt": json.loads(receipt[0]) if receipt else None}

    async def prepare(self, iid, uid):
        self.enabled()
        body = self.invoice(iid, uid)["invoice"]["body"]
        if time.time() > body["expires_at"]:
            raise HTTPException(409, "Invoice expired; start a new checkout")
        gateway = self.gateway
        await gateway.ensure_devnet(gateway.submit_rpc)
        await gateway.ensure_devnet(gateway.verify_rpc)
        rent = (await gateway.submit_rpc.get_minimum_balance_for_rent_exemption(0)).value
        for kind in ("creator", "platform"):
            balance = (await gateway.submit_rpc.get_balance(Pubkey.from_string(body[kind + "_wallet"]))).value
            if balance + body[kind + "_lamports"] < rent:
                raise HTTPException(
                    409,
                    "Payout wallet needs its initial Devnet rent balance; ask the creator to fund it with test SOL before checkout",
                )
        instructions = [
            transfer(
                TransferParams(
                    from_pubkey=Pubkey.from_string(body["payer"]),
                    to_pubkey=Pubkey.from_string(body[k + "_wallet"]),
                    lamports=body[k + "_lamports"],
                )
            )
            for k in ("creator", "platform")
            if body[k + "_lamports"]
        ]
        instructions.append(
            Instruction(Pubkey.from_string(MEMO_PROGRAM), ("tracy-license:" + iid).encode(), [])
        )
        blockhash = (await gateway.submit_rpc.get_latest_blockhash()).value.blockhash
        tx = Transaction.new_unsigned(
            Message.new_with_blockhash(instructions, Pubkey.from_string(body["payer"]), blockhash)
        )
        return {
            "transaction": base64.b64encode(bytes(tx)).decode(),
            "network": "solana-devnet",
            "invoice_id": iid,
        }

    async def submit(self, iid, uid, raw):
        self.enabled()
        body = self.invoice(iid, uid)["invoice"]["body"]
        if time.time() > body["expires_at"]:
            raise HTTPException(409, "Invoice expired")
        try:
            tx = Transaction.from_bytes(base64.b64decode(raw, validate=True))
            tx.verify()
            instructions = [
                transfer(
                    TransferParams(
                        from_pubkey=Pubkey.from_string(body["payer"]),
                        to_pubkey=Pubkey.from_string(body[k + "_wallet"]),
                        lamports=body[k + "_lamports"],
                    )
                )
                for k in ("creator", "platform")
                if body[k + "_lamports"]
            ]
            instructions.append(
                Instruction(Pubkey.from_string(MEMO_PROGRAM), ("tracy-license:" + iid).encode(), [])
            )
            expected = Message.new_with_blockhash(
                instructions, Pubkey.from_string(body["payer"]), tx.message.recent_blockhash
            )
            if bytes(expected) != bytes(tx.message):
                raise ValueError("Message mismatch")
        except Exception as exc:
            raise HTTPException(422, "Signed transaction differs from the invoice") from exc
        await self.gateway.ensure_devnet(self.gateway.submit_rpc)
        await self.gateway.ensure_devnet(self.gateway.verify_rpc)
        from backend.blockchain.solana import PreflightRejected, PreparedTransfer

        try:
            await self.gateway.broadcast(PreparedTransfer(bytes(tx), str(tx.signatures[0])))
        except PreflightRejected as exc:
            raise HTTPException(
                409,
                "Devnet simulation rejected the payment; check test-SOL balances and obtain a fresh transaction",
            ) from exc
        return {"signature": str(tx.signatures[0]), "status": "PENDING", "network": "solana-devnet"}

    async def confirm(self, iid, uid, signature):
        self.enabled()
        prior = self.invoice(iid, uid)
        if prior["receipt"]:
            if prior["receipt"]["body"]["signature"] != signature:
                raise HTTPException(409, "Invoice already settled")
            return prior
        body = prior["invoice"]["body"]
        await self.gateway.ensure_devnet(self.gateway.verify_rpc)
        response = await self.gateway.verify_rpc.get_transaction(
            Signature.from_string(signature),
            encoding="jsonParsed",
            commitment="finalized",
            max_supported_transaction_version=0,
        )
        tx = json.loads(response.to_json())["result"]
        if not tx:
            raise HTTPException(409, "Waiting for a finalized Devnet transaction; retry this signature")
        if not inspect_payment(tx, signature, body):
            raise HTTPException(
                422, "Payment does not match the exact invoice, signer, split, time window and memo"
            )
        receipt = self.a.signed(
            {
                "invoice_hash": prior["invoice"]["hash"],
                "signature": signature,
                "slot": tx["slot"],
                "network": "solana-devnet",
                "creator_lamports": body["creator_lamports"],
                "platform_lamports": body["platform_lamports"],
                "confirmed_at": int(time.time()),
                "status": "PAID",
            }
        )
        with self.db.connect(write=True) as conn:
            used = conn.execute(
                "SELECT invoice_id FROM bundle_payment_receipts WHERE signature=?", (signature,)
            ).fetchone()
            if used and used[0] != iid:
                raise HTTPException(409, "Transaction already used")
            conn.execute(
                "INSERT OR IGNORE INTO bundle_payment_receipts VALUES(?,?,?)",
                (iid, signature, json.dumps(receipt)),
            )
        return self.invoice(iid, uid)
