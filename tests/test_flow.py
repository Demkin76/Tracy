import copy
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from solders.keypair import Keypair

from backend.blockchain.solana import Evidence, PreflightRejected
from backend.crypto.hashing import digest
from backend.receipts.verifier import verify_chain, verify_receipt_crypto


def test_verified_end_to_end_and_fresh_evidence(env):
    request = env.signed()
    response = env.client.post("/v1/actions", json=request)
    assert response.status_code == 201, response.text
    body = response.json()
    receipt = body["receipt"]
    assert body["status"] == receipt["status"] == "VERIFIED"
    assert receipt["previous_receipt_hash"] is None
    assert receipt["sequence"] == 1
    assert env.gateway.prepared[0][1] == 10_000_000
    assert env.gateway.prepared[0][2] == digest({k: v for k, v in request.items() if k != "signature"})
    assert verify_receipt_crypto(receipt, receipt["poa_public_key"]) == (True, True)
    check = env.client.get(f"/v1/receipts/{receipt['receipt_id']}/verify").json()
    assert check["valid"] and check["evidence_valid"] and check["request_signature_valid"]
    assert len(env.gateway.lookups) == 2
    env.gateway.evidence = Evidence("unavailable", "rpc_unavailable")
    check = env.client.get(f"/v1/receipts/{receipt['receipt_id']}/verify").json()
    assert not check["valid"] and check["evidence_valid"] is None
    assert check["signature_valid"] and check["chain_valid"]


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"amount": 5}, "amount_exceeds_limit"),
        ({"action": "solana.swap"}, "action_not_allowed"),
        ({"recipient": str(Keypair().pubkey())}, "recipient_not_allowed"),
    ],
)
def test_policy_rejections_are_signed_without_execution(env, kwargs, reason):
    response = env.client.post("/v1/actions", json=env.signed(**kwargs))
    assert response.status_code == 201
    receipt = response.json()["receipt"]
    assert receipt["status"] == "REJECTED" and receipt["reason"] == reason
    assert not env.gateway.prepared and not env.gateway.broadcasts
    assert env.client.get(f"/v1/receipts/{receipt['receipt_id']}/verify").json()["valid"]


def test_invalid_signature_does_not_reserve_request_id(env):
    request = env.signed(request_id="same_id")
    forged = {**request, "signature": "bad"}
    assert env.client.post("/v1/actions", json=forged).status_code == 401
    assert env.client.post("/v1/actions", json=request).status_code == 201
    assert len(env.gateway.broadcasts) == 1
    with env.db.connect() as conn:
        assert conn.execute("SELECT reason FROM audit_events").fetchone()[0] == "invalid_signature"


def test_tampered_request_rejected(env):
    request = env.signed()
    request["params"]["amount"] = 0.02
    assert env.client.post("/v1/actions", json=request).status_code == 401
    assert not env.gateway.broadcasts


@pytest.mark.parametrize("delta", [-301, 90])
def test_expired_and_future_requests(env, delta):
    assert (
        env.client.post("/v1/actions", json=env.signed(timestamp=int(time.time()) + delta)).status_code == 400
    )
    assert not env.gateway.prepared


def test_unknown_agent(env):
    assert env.client.post("/v1/actions", json=env.signed(agent_id="missing")).status_code == 404


def test_replay_and_parallel_replay_send_once(env):
    request = env.signed()
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: env.client.post("/v1/actions", json=request), range(6)))
    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409, 409, 409]
    assert len(env.gateway.broadcasts) == 1
    for response in responses:
        if response.status_code == 409:
            assert response.json()["detail"]["action_id"]


def test_parallel_receipts_form_one_chain(env):
    requests = [env.signed(amount=2) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda request: env.client.post("/v1/actions", json=request), requests))
    assert all(r.status_code == 201 for r in responses)
    receipts = sorted([r.json()["receipt"] for r in responses], key=lambda r: r["sequence"])
    assert verify_chain(receipts, receipts[0]["poa_public_key"], "agent_test")
    assert env.client.get(f"/v1/receipts/{receipts[-1]['receipt_id']}/verify").json()["chain_valid"]


def test_timeout_reconciliation_never_resends(env):
    env.gateway.broadcast_error = TimeoutError()
    env.gateway.evidence = Evidence("pending", "transaction_not_confirmed")
    request = env.signed()
    response = env.client.post("/v1/actions", json=request)
    assert response.status_code == 202
    action = response.json()
    assert action["receipt"] is None and action["tx_signature"]
    assert env.client.post("/v1/actions", json=request).status_code == 409
    env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 999)
    result = env.client.post(f"/v1/actions/{action['action_id']}/reconcile").json()
    assert result["status"] == "VERIFIED"
    again = env.client.post(f"/v1/actions/{action['action_id']}/reconcile").json()
    assert again["receipt_id"] == result["receipt_id"]
    assert len(env.gateway.prepared) == len(env.gateway.broadcasts) == 1


@pytest.mark.parametrize("status", ["mismatch", "failed"])
def test_bad_chain_evidence_never_verified(env, status):
    env.gateway.evidence = Evidence(status, "test_mismatch", 10)
    receipt = env.client.post("/v1/actions", json=env.signed()).json()["receipt"]
    assert receipt["status"] == "FAILED"
    assert receipt["verification"]["status"] == status
    assert not env.client.get(f"/v1/receipts/{receipt['receipt_id']}/verify").json()["valid"]


def test_preparation_failure_and_preflight_rejection(env):
    env.gateway.prepare_error = RuntimeError("wrong network")
    receipt = env.client.post("/v1/actions", json=env.signed()).json()["receipt"]
    assert receipt["reason"] == "preparation_failed" and not env.gateway.broadcasts
    env.gateway.prepare_error = None
    env.gateway.broadcast_error = PreflightRejected()
    receipt = env.client.post("/v1/actions", json=env.signed()).json()["receipt"]
    assert receipt["status"] == "FAILED" and receipt["reason"] == "preflight_rejected"


@pytest.mark.parametrize("amount", [0, -0.1, 0.0000000001, True, "0.01", 1000001])
def test_invalid_amounts_rejected_before_execution(env, amount):
    request = env.signed()
    request["params"]["amount"] = amount
    assert env.client.post("/v1/actions", json=request).status_code == 422
    assert not env.gateway.broadcasts


def test_schema_is_strict_and_rejections_audited(env):
    request = env.signed()
    request["extra"] = "unexpected"
    assert env.client.post("/v1/actions", json=request).status_code == 422
    assert env.client.post("/v1/actions", content="{bad").status_code == 422
    assert (
        env.client.post(
            "/v1/agents", json=env.registration, headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )
    with env.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM audit_events").fetchone()[0] >= 2


def test_tamper_detection_and_append_only(env):
    receipt = env.client.post("/v1/actions", json=env.signed()).json()["receipt"]
    tampered = copy.deepcopy(receipt)
    tampered["requested"]["amount"] = 10
    assert verify_receipt_crypto(tampered, receipt["poa_public_key"])[0] is False
    tampered["receipt_hash"] = digest(
        {k: v for k, v in tampered.items() if k not in ("receipt_hash", "poa_signature")}
    )
    assert verify_receipt_crypto(tampered, receipt["poa_public_key"]) == (True, False)
    assert not verify_chain([tampered], receipt["poa_public_key"], "agent_test")
    for sql in ["UPDATE receipts SET sequence=9", "DELETE FROM receipts"]:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"), env.db.connect(write=True) as conn:
            conn.execute(sql)


def test_missing_chain_entry_detected(env):
    receipts = [env.client.post("/v1/actions", json=env.signed(amount=2)).json()["receipt"] for _ in range(3)]
    assert not verify_chain(receipts[1:], receipts[0]["poa_public_key"], "agent_test")
    assert not verify_chain([receipts[0], receipts[2]], receipts[0]["poa_public_key"], "agent_test")


def test_persisted_history_and_key_pin(env):
    body = env.client.post("/v1/actions", json=env.signed()).json()
    history = env.client.get("/v1/agents/agent_test/actions").json()
    assert history["total"] == 1 and history["counts"]["VERIFIED"] == 1
    assert env.client.get("/v1/actions/" + body["action_id"]).json()["receipt_id"] == body["receipt_id"]
    with pytest.raises(RuntimeError, match="differs"):
        env.db.initialize("wrong key", env.gateway.sender)
    with env.db.connect() as conn:
        record = json.loads(conn.execute("SELECT body FROM receipts").fetchone()[0])
    assert record == body["receipt"]
