"""Wallet-signed Raydium CPMM Devnet execution, separate from paper performance.

ABI: raydium-io/raydium-sdk-V2 src/raydium/cpmm/{layout,instruction}.ts.
Only legacy SPL pools without creator fees/extensions are supported, fail closed.
"""

import base64
import hashlib
import json
import struct
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import (
    create_idempotent_associated_token_account,
    get_associated_token_address,
    sync_native,
)
from spl.token.models import SyncNativeParams

from backend.adaptive.payments import Checkout
from backend.blockchain.solana import MEMO_PROGRAM, PreparedTransfer
from backend.execution_control import require_execution

PROGRAM = "DRaycpLY18LhpbydsBWbVJtxpNv9oXPgjRSfpF2bWpYb"
AUTHORITY = "CXniRufdq5xL8t8jZAPxsPZDpuudwuJSPWnbcD5Y5Nxq"
WSOL = "So11111111111111111111111111111111111111112"
POOL = "Bw9gaeKqQy5aTpi1BiSdV2p21REATtVXDdhjPUFjgq6N"
TOKEN = "9jWfcfEZToquBQmkoEViNSCt72veXwcvRGFQERXRjEk1"
SWAP = bytes([143, 190, 90, 218, 196, 30, 51, 222])


class SwapRequest(Checkout):
    side: str = Field(pattern="^(BUY|SELL)$")
    amount_raw: int = Field(ge=1, le=10**12, strict=True)
    slippage_bps: int = Field(default=50, ge=1, le=100, strict=True)


def u64(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def key(data, offset):
    return str(Pubkey.from_bytes(data[offset : offset + 32]))


def decode_pool(data):
    if len(data) != 637 or data[:8] != hashlib.sha256(b"account:PoolState").digest()[:8]:
        raise ValueError("Unknown CPMM account layout")
    if data[329] != 0 or data[390] != 0:
        raise ValueError("Pool status or creator fee not supported")
    names = (
        "config",
        "creator",
        "vault_a",
        "vault_b",
        "lp_mint",
        "mint_a",
        "mint_b",
        "program_a",
        "program_b",
        "observation",
    )
    result = {name: key(data, 8 + 32 * i) for i, name in enumerate(names)}
    if {result["mint_a"], result["mint_b"]} != {WSOL, TOKEN}:
        raise ValueError("Unexpected pool mints")
    if result["program_a"] != str(TOKEN_PROGRAM_ID) or result["program_b"] != str(TOKEN_PROGRAM_ID):
        raise ValueError("Token extensions unsupported")
    result.update(
        fees_a=u64(data, 341) + u64(data, 357) + u64(data, 397),
        fees_b=u64(data, 349) + u64(data, 365) + u64(data, 405),
        open_time=u64(data, 373),
    )
    return result


def quote_amount(amount, reserve_in, reserve_out, fee, slippage):
    if reserve_in <= 0 or reserve_out <= 0 or not 0 <= fee <= 10000:
        raise ValueError("Unsupported liquidity or fee")
    fee_amount = (amount * fee + 999999) // 1000000
    effective = amount - fee_amount
    output = effective * reserve_out // (reserve_in + effective)
    minimum = output * (10000 - slippage) // 10000
    if minimum <= 0 or amount * 100 > reserve_in:
        raise ValueError("Trade too small or exceeds 1% of pool reserves")
    return output, minimum, fee_amount


class DevnetDex:
    def __init__(self, adaptive, gateway):
        self.a, self.db, self.g = adaptive, adaptive.db, gateway

    def enabled(self):
        if not self.a.s.settings.adaptive_devnet_dex_enabled:
            raise HTTPException(409, "Devnet DEX execution is disabled")
        require_execution(self.a.s.settings)

    async def quote(self, uid, payload):
        self.enabled()
        await self.g.ensure_devnet(self.g.submit_rpc)
        await self.g.ensure_devnet(self.g.verify_rpc)
        try:
            account = (await self.g.submit_rpc.get_account_info(Pubkey.from_string(POOL))).value
            if not account or str(account.owner) != PROGRAM:
                raise ValueError("Pool owner mismatch")
            p = decode_pool(account.data)
            if p["open_time"] > time.time():
                raise ValueError("Pool not open")
            keys = [p[k] for k in ("config", "vault_a", "vault_b", "mint_a", "mint_b")]
            response = await self.g.submit_rpc.get_multiple_accounts([Pubkey.from_string(k) for k in keys])
            config, va, vb, ma, mb = response.value
            if not all(response.value) or str(config.owner) != PROGRAM:
                raise ValueError("Missing accounts")
            for account, mint in ((va, p["mint_a"]), (vb, p["mint_b"])):
                if (
                    str(account.owner) != str(TOKEN_PROGRAM_ID)
                    or len(account.data) != 165
                    or key(account.data, 0) != mint
                    or key(account.data, 32) != AUTHORITY
                ):
                    raise ValueError("Vault mismatch")
            if any(str(m.owner) != str(TOKEN_PROGRAM_ID) or len(m.data) != 82 for m in (ma, mb)):
                raise ValueError("Mint extensions unsupported")
            reserves = [u64(va.data, 64) - p["fees_a"], u64(vb.data, 64) - p["fees_b"]]
            input_mint = WSOL if payload.side == "BUY" else TOKEN
            idx = 0 if p["mint_a"] == input_mint else 1
            if payload.amount_raw * reserves[0 if p["mint_a"] == WSOL else 1] // reserves[idx] > 1_000_000:
                raise ValueError("Maximum swap size is 0.001 test SOL equivalent")
            output, minimum, fee = quote_amount(
                payload.amount_raw,
                reserves[idx],
                reserves[1 - idx],
                u64(config.data, 12),
                payload.slippage_bps,
            )
        except (ValueError, TypeError, AttributeError, ZeroDivisionError, struct.error) as exc:
            raise HTTPException(409, str(exc)) from exc
        payer = Pubkey.from_string(payload.payer)
        mints = [input_mint, TOKEN if input_mint == WSOL else WSOL]
        atas = [get_associated_token_address(payer, Pubkey.from_string(m)) for m in mints]
        instructions = [
            create_idempotent_associated_token_account(payer, payer, Pubkey.from_string(m)) for m in mints
        ]
        if payload.side == "BUY":
            instructions += [
                transfer(TransferParams(from_pubkey=payer, to_pubkey=atas[0], lamports=payload.amount_raw)),
                sync_native(SyncNativeParams(program_id=TOKEN_PROGRAM_ID, account=atas[0])),
            ]
        vaults = [p["vault_a"], p["vault_b"]]
        accounts = [
            (payload.payer, True, True),
            (AUTHORITY, False, False),
            (p["config"], False, False),
            (POOL, False, True),
            (str(atas[0]), False, True),
            (str(atas[1]), False, True),
            (vaults[idx], False, True),
            (vaults[1 - idx], False, True),
            (str(TOKEN_PROGRAM_ID), False, False),
            (str(TOKEN_PROGRAM_ID), False, False),
            (mints[0], False, False),
            (mints[1], False, False),
            (p["observation"], False, True),
        ]
        instructions.append(
            Instruction(
                Pubkey.from_string(PROGRAM),
                SWAP + struct.pack("<QQ", payload.amount_raw, minimum),
                [AccountMeta(Pubkey.from_string(k), s, w) for k, s, w in accounts],
            )
        )
        qid = "swap_" + uuid4().hex
        instructions.append(
            Instruction(Pubkey.from_string(MEMO_PROGRAM), ("tracy-devnet-swap:" + qid).encode(), [])
        )
        blockhash = (await self.g.submit_rpc.get_latest_blockhash()).value.blockhash
        tx = Transaction.new_unsigned(Message.new_with_blockhash(instructions, payer, blockhash))
        body = {
            "swap_id": qid,
            "network": "solana-devnet",
            "pool": POOL,
            "payer": payload.payer,
            "side": payload.side,
            "input_mint": mints[0],
            "output_mint": mints[1],
            "amount_raw": payload.amount_raw,
            "quoted_output_raw": output,
            "minimum_output_raw": minimum,
            "fee_raw": fee,
            "slippage_bps": payload.slippage_bps,
            "source_slot": response.context.slot,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + 90,
            "transaction": base64.b64encode(bytes(tx)).decode(),
            "output_account": str(atas[1]),
            "note": "Test tokens only. Seller receives wrapped test SOL. ATA creation rent and network fees are additional. Not a real-market performance observation.",
        }
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO devnet_swaps VALUES(?,?,?,NULL)", (qid, uid, json.dumps(self.a.signed(body)))
            )
        return self.get(qid, uid)

    def get(self, qid, uid):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT body,receipt FROM devnet_swaps WHERE swap_id=? AND owner_id=?", (qid, uid)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Swap not found")
        envelope = json.loads(row[0])
        self.a.checked(envelope)
        receipt = json.loads(row[1]) if row[1] else None
        if receipt:
            self.a.checked(receipt)
        return {"quote": envelope, "receipt": receipt}

    async def submit(self, qid, uid, raw):
        self.enabled()
        record = self.get(qid, uid)
        body = record["quote"]["body"]
        if time.time() > body["expires_at"]:
            raise HTTPException(409, "Quote expired; obtain a new quote")
        try:
            tx = Transaction.from_bytes(base64.b64decode(raw, validate=True))
            tx.verify()
            expected = Transaction.from_bytes(base64.b64decode(body["transaction"]))
            if bytes(tx.message) != bytes(expected.message):
                raise ValueError("Message mismatch")
        except Exception as exc:
            raise HTTPException(422, "Signed swap differs from the reviewed quote") from exc
        await self.g.ensure_devnet(self.g.submit_rpc)
        await self.g.ensure_devnet(self.g.verify_rpc)
        from backend.blockchain.solana import PreflightRejected

        try:
            await self.g.broadcast(PreparedTransfer(bytes(tx), str(tx.signatures[0])))
        except PreflightRejected as exc:
            raise HTTPException(
                409, "Devnet swap simulation rejected; check balances, rent and quote freshness"
            ) from exc
        return {"signature": str(tx.signatures[0]), "status": "PENDING"}

    async def confirm(self, qid, uid, signature):
        self.enabled()
        prior = self.get(qid, uid)
        body = prior["quote"]["body"]
        if prior["receipt"]:
            if prior["receipt"]["body"]["signature"] != signature:
                raise HTTPException(409, "Swap already confirmed")
            return prior
        await self.g.ensure_devnet(self.g.verify_rpc)
        response = await self.g.verify_rpc.get_transaction(
            Signature.from_string(signature),
            encoding="base64",
            commitment="finalized",
            max_supported_transaction_version=0,
        )
        result = json.loads(response.to_json())["result"]
        if not result:
            raise HTTPException(409, "Waiting for a finalized Devnet swap")
        try:
            tx = Transaction.from_bytes(base64.b64decode(result["transaction"][0]))
            tx.verify()
            expected = Transaction.from_bytes(base64.b64decode(body["transaction"]))
            if (
                result["meta"]["err"] is not None
                or str(tx.signatures[0]) != signature
                or bytes(tx.message) != bytes(expected.message)
            ):
                raise ValueError("Swap did not execute as reviewed")
            index = list(map(str, tx.message.account_keys)).index(body["output_account"])

            def balance(items):
                return sum(
                    int(i["uiTokenAmount"]["amount"])
                    for i in items
                    if i["accountIndex"] == index
                    and i["mint"] == body["output_mint"]
                    and i.get("owner") == body["payer"]
                )

            output = balance(result["meta"]["postTokenBalances"]) - balance(
                result["meta"]["preTokenBalances"]
            )
            if output < body["minimum_output_raw"]:
                raise ValueError("Output balance does not meet the minimum")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "Swap evidence mismatch") from exc
        receipt = self.a.signed(
            {
                "quote_hash": prior["quote"]["hash"],
                "signature": signature,
                "slot": result["slot"],
                "output_raw": output,
                "network_fee_lamports": result["meta"]["fee"],
                "status": "CONFIRMED",
                "network": "solana-devnet",
                "execution": "raydium_cpmm_devnet",
            }
        )
        with self.db.connect(write=True) as conn:
            conn.execute(
                "UPDATE devnet_swaps SET receipt=? WHERE swap_id=? AND receipt IS NULL",
                (json.dumps(receipt), qid),
            )
        return self.get(qid, uid)
