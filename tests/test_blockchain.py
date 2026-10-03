import copy
from unittest.mock import AsyncMock

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction

from backend.blockchain.solana import (
    DEVNET_GENESIS_HASH,
    MEMO_PROGRAM,
    SYSTEM_PROGRAM,
    SolanaGateway,
    inspect_transaction,
)

SENDER, RECIPIENT, SIG, REQUEST_HASH = "sender", "recipient", "signature", "a" * 64


def rpc_transaction():
    return {
        "slot": 42,
        "transaction": {
            "signatures": [SIG],
            "message": {
                "accountKeys": [
                    {"pubkey": SENDER, "signer": True, "writable": True},
                    {"pubkey": RECIPIENT, "signer": False, "writable": True},
                ],
                "instructions": [
                    {
                        "programId": SYSTEM_PROGRAM,
                        "parsed": {
                            "type": "transfer",
                            "info": {"source": SENDER, "destination": RECIPIENT, "lamports": 100},
                        },
                    },
                    {"programId": MEMO_PROGRAM, "parsed": "poa:" + REQUEST_HASH},
                ],
            },
        },
        "meta": {
            "err": None,
            "fee": 5,
            "preBalances": [1000, 200],
            "postBalances": [895, 300],
            "innerInstructions": [],
        },
    }


def inspect(tx):
    return inspect_transaction(tx, SIG, SENDER, RECIPIENT, 100, REQUEST_HASH)


def test_actual_rpc_evidence_parser():
    assert inspect(rpc_transaction()).status == "verified"
    assert inspect(None).status == "pending"
    assert inspect({}).status == "unavailable"


@pytest.mark.parametrize("field,value", [("source", "wrong"), ("destination", "wrong"), ("lamports", 101)])
def test_rpc_transfer_mismatch(field, value):
    tx = rpc_transaction()
    tx["transaction"]["message"]["instructions"][0]["parsed"]["info"][field] = value
    assert inspect(tx).status == "mismatch"


def test_rpc_failed_missing_metadata_balance_and_memo():
    tx = rpc_transaction()
    tx["meta"]["err"] = {"InstructionError": [0, "InsufficientFunds"]}
    assert inspect(tx).status == "failed"
    tx["meta"] = None
    assert inspect(tx).status == "unavailable"
    tx = rpc_transaction()
    tx["meta"]["postBalances"][1] += 1
    assert inspect(tx).status == "mismatch"
    tx = rpc_transaction()
    tx["transaction"]["message"]["instructions"][1]["parsed"] = "poa:other"
    assert inspect(tx).reason == "request_binding_mismatch"


def test_extra_instruction_or_wrong_signer():
    tx = rpc_transaction()
    tx["transaction"]["message"]["instructions"].append(
        copy.deepcopy(tx["transaction"]["message"]["instructions"][0])
    )
    assert inspect(tx).status == "mismatch"
    tx = rpc_transaction()
    tx["transaction"]["message"]["accountKeys"][0]["signer"] = False
    assert inspect(tx).status == "mismatch"


async def test_transaction_contains_request_memo_and_valid_signature(env):
    gateway = SolanaGateway(env.settings)
    gateway.ensure_devnet = AsyncMock()
    from types import SimpleNamespace

    gateway.submit_rpc.get_latest_blockhash = AsyncMock(
        return_value=SimpleNamespace(value=SimpleNamespace(blockhash=Hash.new_unique()))
    )
    first = await gateway.prepare(str(Keypair().pubkey()), 100, "a" * 64)
    transaction = Transaction.from_bytes(first.raw)
    transaction.verify()
    assert len(transaction.message.instructions) == 2
    assert bytes(transaction.message.instructions[1].data) == b"poa:" + b"a" * 64
    assert str(transaction.signatures[0]) == first.signature
    second = await gateway.prepare(env.recipient, 100, "b" * 64)
    third = await gateway.prepare(env.recipient, 100, "c" * 64)
    assert second.signature != third.signature
    await gateway.close()


async def test_wrong_network_refused(env):
    from types import SimpleNamespace

    gateway = SolanaGateway(env.settings)
    gateway.submit_rpc.get_genesis_hash = AsyncMock(return_value=SimpleNamespace(value="wrong-network"))
    with pytest.raises(RuntimeError, match="not Solana Devnet"):
        await gateway.prepare(env.recipient, 100, REQUEST_HASH)
    gateway.submit_rpc.get_genesis_hash = AsyncMock(return_value=SimpleNamespace(value=DEVNET_GENESIS_HASH))
    await gateway.ensure_devnet(gateway.submit_rpc)
    await gateway.close()
