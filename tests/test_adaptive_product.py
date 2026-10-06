import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from solders.keypair import Keypair

from backend.adaptive.dex import decode_pool, quote_amount
from backend.adaptive.payments import inspect_payment
from backend.blockchain.solana import MEMO_PROGRAM, SYSTEM_PROGRAM
from tests.test_adaptive import create, train
from tests.test_platform import other_account


def test_expanded_pine_compiler_rejects_semantic_changes(env):
    source = """//@version=5
strategy("EMA", overlay=true)
fLen = input.int(5, "Fast")
sLen = input.int(20, "Slow")
a = ta.ema(close, fLen)
b = ta.ema(close, sLen)
enter = ta.crossover(a, b)
exit = ta.crossunder(a, b)
if enter
    strategy.entry("L", strategy.long)
if exit
    strategy.close("L")
plot(a, "Fast")
"""
    r = env.client.post("/v1/adaptive/import-pine", json={"source": source})
    assert r.status_code == 200 and r.json()["program"]["kind"] == "ema_cross"
    for invalid in [
        source + '\nstrategy.exit("stop", stop=100)',
        source.replace("if exit", "if enter"),
        source.replace("close, sLen", "open, sLen"),
    ]:
        assert env.client.post("/v1/adaptive/import-pine", json={"source": invalid}).status_code == 422


def test_unified_catalog_creator_and_private_comparison(env):
    a = create(env)
    train(env, a)
    path = f"/v1/adaptive/agents/{a['agent_id']}/bundles?revision=2"
    b = env.client.post(path).json()
    bid = b["bundle_id"]
    assert env.client.get("/v1/public/catalog").json()["items"] == []
    env.client.put(f"/v1/adaptive/bundles/{bid}/publication", json={"listed": True})
    item = env.client.get("/v1/public/catalog").json()["items"][0]
    assert item["creator_name"] == env.user["name"] and "email" not in item
    assert (
        env.client.get("/v1/public/creators/" + item["creator_id"]).json()["metrics"]["public_bundles"] == 1
    )
    clones = [
        env.client.post(f"/v1/adaptive/bundles/{bid}/clone", json={"name": f"Clone {i}"}).json()
        for i in range(2)
    ]
    url = f"/v1/adaptive/compare?first={clones[0]['agent_id']}&second={clones[1]['agent_id']}"
    assert env.client.get(url).status_code == 200
    other = TestClient(env.app)
    other_account(other)
    assert other.get(url).status_code == 404
    assert env.client.get(f"/v1/public/bundles/{bid}/intelligence").json()["rules"] == []
    other.close()


def transaction(invoice, signature):
    return {
        "slot": 1,
        "blockTime": invoice["created_at"] + 1,
        "meta": {"err": None},
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [{"pubkey": invoice["payer"], "signer": True}],
                "instructions": [
                    {
                        "programId": SYSTEM_PROGRAM,
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": invoice["payer"],
                                "destination": invoice[k + "_wallet"],
                                "lamports": invoice[k + "_lamports"],
                            },
                        },
                    }
                    for k in ("creator", "platform")
                ]
                + [{"programId": MEMO_PROGRAM, "parsed": "tracy-license:" + invoice["invoice_id"]}],
            },
        },
    }


def test_exact_split_payment_and_owner_bound_license(env, monkeypatch):
    a = create(env)
    train(env, a)
    b = env.client.post(f"/v1/adaptive/agents/{a['agent_id']}/bundles?revision=2").json()
    bid = b["bundle_id"]
    env.client.put(f"/v1/adaptive/bundles/{bid}/publication", json={"listed": True})
    payments = env.app.state.adaptive.payments
    monkeypatch.setattr(payments.a.s.settings, "adaptive_devnet_payments_enabled", True)
    creator, payer = str(Keypair().pubkey()), str(Keypair().pubkey())
    assert (
        env.client.put(
            f"/v1/adaptive/bundles/{bid}/price", json={"lamports": 100000, "creator_wallet": creator}
        ).status_code
        == 200
    )
    buyer = TestClient(env.app)
    other_account(buyer)
    assert buyer.post(f"/v1/adaptive/bundles/{bid}/clone", json={"name": "Paid copy"}).status_code == 402
    invoice = buyer.post(f"/v1/adaptive/bundles/{bid}/checkout", json={"payer": payer}).json()["invoice"][
        "body"
    ]
    assert invoice["creator_lamports"] == 95000 and invoice["platform_lamports"] == 5000
    signature = str(Keypair().sign_message(b"test"))
    tx = transaction(invoice, signature)
    assert inspect_payment(tx, signature, invoice)
    for tamper in ("amount", "signer", "memo", "failure", "time"):
        altered = deepcopy(tx)
        if tamper == "amount":
            altered["transaction"]["message"]["instructions"][0]["parsed"]["info"]["lamports"] -= 1
        if tamper == "signer":
            altered["transaction"]["message"]["accountKeys"][0]["pubkey"] = creator
        if tamper == "memo":
            altered["transaction"]["message"]["instructions"][-1]["parsed"] = "wrong"
        if tamper == "failure":
            altered["meta"]["err"] = {}
        if tamper == "time":
            altered["blockTime"] = invoice["expires_at"] + 100
        assert not inspect_payment(altered, signature, invoice)

    async def ensure(_):
        pass

    async def get(*args, **kwargs):
        return SimpleNamespace(to_json=lambda: json.dumps({"result": tx}))

    payments.gateway = SimpleNamespace(ensure_devnet=ensure, verify_rpc=SimpleNamespace(get_transaction=get))
    iid = invoice["invoice_id"]
    path = f"/v1/adaptive/invoices/{iid}/confirm"
    assert env.client.post(path, json={"signature": signature}).status_code == 404
    assert buyer.post(path, json={"signature": signature}).status_code == 200
    assert buyer.post(path, json={"signature": signature}).status_code == 200
    assert buyer.post(f"/v1/adaptive/bundles/{bid}/clone", json={"name": "Paid copy"}).status_code == 201
    buyer.close()


def test_dex_quote_limits():
    output, minimum, fee = quote_amount(100000, 10**12, 10**11, 2500, 50)
    assert output > minimum > 0 and fee == 250
    with pytest.raises(ValueError):
        quote_amount(100, 100, 100, 2500, 50)
    with pytest.raises(ValueError):
        decode_pool(b"unsupported")
