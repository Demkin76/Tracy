import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.blockchain.solana import Evidence
from backend.main import create_app


@pytest.mark.parametrize("amount,status", [(0.01, "FAILED"), (2, "REJECTED")])
def test_restart_recovers_unsubmitted_without_false_policy_approval(env, amount, status):
    request = env.signed(amount=amount)
    with env.db.connect(write=True) as conn:
        conn.execute(
            "INSERT INTO actions(action_id,agent_id,request_id,request,policy,sender,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                "act_interrupted",
                "agent_test",
                request["request_id"],
                json.dumps(request),
                json.dumps(env.registration["policy"]),
                env.gateway.sender,
                "PREPARING",
                int(time.time()),
            ),
        )
    with TestClient(create_app(env.settings, env.gateway), headers=dict(env.client.headers)) as restarted:
        result = restarted.get("/v1/actions/act_interrupted").json()
        assert result["status"] == status
        assert result["receipt"]["policy"]["approved"] == (status != "REJECTED")
        assert restarted.post("/v1/actions", json=request).status_code == 409
        assert not env.gateway.broadcasts


def test_restart_reconciles_known_signature_without_resubmission(env):
    env.gateway.evidence = Evidence("pending", "not_yet_confirmed")
    request = env.signed()
    result = env.client.post("/v1/actions", json=request).json()
    with TestClient(create_app(env.settings, env.gateway), headers=dict(env.client.headers)) as restarted:
        assert restarted.get("/v1/actions/" + result["action_id"]).json()["status"] == "PENDING"
        env.gateway.evidence = Evidence("verified", "exact_transfer_confirmed", 12)
        reconciled = restarted.post("/v1/actions/" + result["action_id"] + "/reconcile").json()
        assert reconciled["status"] == "VERIFIED"
        assert reconciled["tx_signature"] == result["tx_signature"]
        assert len(env.gateway.broadcasts) == len(env.gateway.prepared) == 1


def test_one_lamport_survives_signature_and_conversion(env):
    response = env.client.post("/v1/actions", json=env.signed(amount=0.000000001))
    assert response.status_code == 201
    assert env.gateway.prepared[0][1] == 1
    assert response.json()["receipt"]["requested"]["amount"] == 1e-9
