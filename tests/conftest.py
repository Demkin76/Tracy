from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from solders.keypair import Keypair
from solders.signature import Signature

from backend.blockchain.solana import Evidence, PreparedTransfer
from backend.config import Settings
from backend.main import create_app
from sdk.poa.signing import generate_keypair, sign_request


class FakeGateway:
    """Deterministic test double; never selectable in the production configuration."""

    def __init__(self):
        self.sender = str(Keypair().pubkey())
        self.prepared = []
        self.broadcasts = []
        self.lookups = []
        self.evidence = Evidence("verified", "exact_transfer_confirmed", 123)
        self.prepare_error = None
        self.broadcast_error = None

    async def prepare(self, recipient, lamports, request_hash):
        if self.prepare_error:
            raise self.prepare_error
        self.prepared.append((recipient, lamports, request_hash))
        return PreparedTransfer(b"test", str(Signature.new_unique()))

    async def broadcast(self, prepared):
        self.broadcasts.append(prepared)
        if self.broadcast_error:
            raise self.broadcast_error

    async def verify_transfer(self, *args):
        self.lookups.append(args)
        return self.evidence

    async def health(self):
        return {"rpc_available": True, "balance_lamports": 1_000_000_000}

    async def close(self):
        pass


@pytest.fixture
def env(tmp_path):
    keys = generate_keypair()
    gateway = FakeGateway()
    recipient = str(Keypair().pubkey())
    settings = Settings(
        _env_file=None,
        admin_token="test-admin-token-long-enough",
        signing_seed=generate_keypair()["private_seed"],
        execution_wallet_seed=generate_keypair()["private_seed"],
        database_path=tmp_path / "test.sqlite3",
        reconciler_enabled=False,
        verification_attempts=1,
        verification_interval_seconds=0,
    )
    app = create_app(settings, gateway)
    with TestClient(app) as client:
        signup = client.post(
            "/v1/auth/signup",
            json={"email": "owner@example.test", "password": "long-test-password", "name": "Test owner"},
        )
        assert signup.status_code == 201, signup.text
        csrf = signup.json()["csrf_token"]
        key = client.post(
            "/v1/account/api-keys", json={"name": "Tests"}, headers={"X-CSRF-Token": csrf}
        ).json()
        client.headers["Authorization"] = "Bearer " + key["token"]
        registration = {
            "agent_id": "agent_test",
            "name": "Test agent",
            "public_key": keys["public_key"],
            "policy": {
                "allowed_actions": ["solana.transfer"],
                "max_transfer_sol": 0.1,
                "allowed_recipients": [recipient],
            },
        }
        assert (
            client.post(
                "/v1/agents",
                json=registration,
            ).status_code
            == 201
        )

        def signed(**kwargs):
            return sign_request(
                keys["private_seed"],
                kwargs.pop("agent_id", "agent_test"),
                kwargs.pop("recipient", recipient),
                kwargs.pop("amount", 0.01),
                **kwargs,
            )

        yield SimpleNamespace(
            client=client,
            app=app,
            db=app.state.db,
            settings=settings,
            gateway=gateway,
            recipient=recipient,
            keys=keys,
            signed=signed,
            registration=registration,
            user=signup.json()["user"],
        )


@pytest.fixture(autouse=True)
def recorded_market_transport(monkeypatch):
    """Deterministic exchange transport for unit tests only; live smoke uses the real API."""
    from backend.market_data.provider import SECONDS, MarketData
    from tests.market_data_fixture import candles

    def fetch(self, params):
        count, start = params["limit"], params["startTime"] // 1000
        market = params["symbol"].removesuffix("USDC") + "/USDC"
        timeframe = params["interval"]
        step = SECONDS[timeframe]
        result = []
        for offset in range(0, count, 96):
            dataset = "stress" if offset + 96 >= count else "trending"
            bars = candles(market, timeframe, start + offset * step, min(96, count - offset), dataset)
            for bar in bars:
                price = bar["price"]
                result.append([bar["timestamp"] * 1000, str(price), str(price * 1.01), str(price * .99), str(price), "100", (bar["timestamp"] + step) * 1000 - 1, str(price * 100), 10])
        return result

    monkeypatch.setattr(MarketData, "_fetch", fetch)
