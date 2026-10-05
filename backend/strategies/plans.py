"""Test an immutable intent/configuration snapshot before creating an agent."""

import json
import sqlite3
import time
from copy import deepcopy
from typing import Literal
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StrictBool, field_validator, model_validator

from backend.actions.models import StrictModel
from backend.control.models import Policy
from backend.crypto.hashing import digest
from backend.crypto.signatures import encode_base64, public_key, sign
from backend.market_data.provider import provenance
from backend.platform.service import record_event
from backend.strategies.models import VersionInput
from backend.trading.adapters import run_backtest


class AgentPlan(VersionInput):
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=10, max_length=1000)
    source_strategy_id: str | None = Field(default=None, max_length=120)
    source_version: int | None = Field(default=None, ge=1)
    risk_tolerance: Literal["low", "medium", "high"] = "low"
    forbidden: list[Literal["leverage", "withdrawals", "short_selling"]] = Field(
        default_factory=lambda: ["leverage", "withdrawals", "short_selling"]
    )

    @field_validator("name", "goal")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a name and an intent")
        return value.strip()

    @model_validator(mode="after")
    def coherent(self):
        if bool(self.source_strategy_id) != bool(self.source_version):
            raise ValueError("Source strategy and version must be supplied together")
        g = self.guardrails
        if set(self.forbidden) != {"leverage", "withdrawals", "short_selling"}:
            raise ValueError("Paper agents cannot use leverage, withdraw or sell short")
        if g.allowed_markets != [self.market] or g.allowed_tokens != self.symbols:
            raise ValueError("Permissions must match the reviewed market and assets")
        if not g.max_trade_size <= g.max_position_size <= self.starting_capital:
            raise ValueError("Trade limit must not exceed position limit or capital")
        entry = self.starting_capital * self.strategy_config.allocation_pct / 100
        if entry > g.max_trade_size:
            raise ValueError("Capital per entry exceeds the trade limit; reduce allocation")
        return self


class PlanDeployment(StrictModel):
    reviewed_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledged: StrictBool


def policy_checks(service, value, context):
    """Exercise the production admission evaluator against a disposable ledger."""
    strategy = {**value, "agent_id": "preview", "strategy_id": "preview", "version": 1, "status": "LIVE"}
    deployment = {"deployment_id": "preview", "strategy_version": 1, "status": "LIVE", "step": 0}
    rules = value["guardrails"]
    slip = 1 + value["strategy_config"]["slippage_bps"] / 10000
    amount = min(rules["max_trade_size"], rules["max_position_size"], value["starting_capital"]) / 10
    order = {
        "strategy_version": 1,
        "side": "BUY",
        "quantity": amount / context["price"] / slip,
        "requested_price": context["price"],
        "max_slippage_bps": 100,
    }
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript("""
            CREATE TABLE agents(agent_id TEXT, active INTEGER, status_version INTEGER);
            INSERT INTO agents VALUES('preview',1,1);
            CREATE TABLE paper_fills(deployment_id TEXT, body TEXT);
            CREATE TABLE trading_marks(deployment_id TEXT, step INTEGER, body TEXT);
            CREATE TABLE trading_intents(deployment_id TEXT,status TEXT,intent_id TEXT,request TEXT);
        """)
        rows = []

        def check(label, candidate, expected, s=None):
            decision, reason, observation = service.trading.evaluate(
                conn, s or strategy, deployment, candidate, context
            )
            rows.append(
                {
                    "name": label,
                    "passed": decision in expected,
                    "decision": decision,
                    "reason": reason,
                    "expected": sorted(expected),
                    "input": {
                        "order": candidate,
                        "market": (s or strategy)["market"],
                        "guardrails": (s or strategy)["guardrails"],
                        "agent_active": bool(conn.execute("SELECT active FROM agents").fetchone()[0]),
                        "portfolio_basis": "Constructed boundary-test ledger",
                    },
                    "observed": observation,
                }
            )

        check(
            "Within-limit order follows autonomy rule",
            order,
            {"review"} if amount > rules["human_approval_above"] else {"allow"},
        )
        check(
            "Oversized order is blocked",
            {**order, "quantity": rules["max_trade_size"] * 2 / context["price"]},
            {"deny"},
        )
        excluded = deepcopy(strategy)
        excluded["market"] = "ETH/USDC" if value["market"] != "ETH/USDC" else "BTC/USDC"
        check("Unapproved market is blocked", order, {"deny"}, excluded)
        check("Selling without inventory is blocked", {**order, "side": "SELL"}, {"deny"})
        above = max(rules["human_approval_above"] * 1.01, 0.01)
        check(
            "Above-threshold order cannot execute automatically",
            {**order, "quantity": above / context["price"] / slip},
            {"review", "deny"},
        )
        # Exercise additional decision branches with the user's actual limits.
        check("Paused deployment cannot execute", order, {"deny"}, {**strategy, "status": "PAUSED"})
        check("Stale strategy version is blocked", {**order, "strategy_version": 2}, {"deny"})
        check(
            "Slippage above request tolerance is blocked",
            {**order, "requested_price": context["price"] / 2},
            {"deny"},
        )

        def ledger_loss(loss_pct, previous_day=False):
            conn.execute("DELETE FROM paper_fills")
            conn.execute("DELETE FROM trading_marks")
            timestamp = context["timestamp"] - (86400 if previous_day else 0) - 2
            cash = value["starting_capital"]
            quantity = cash / context["price"]
            for index, side in enumerate(("BUY", "SELL")):
                price = context["price"] * (1 if side == "BUY" else 1 - loss_pct / 100)
                fill = {
                    "side": side,
                    "quantity": quantity,
                    "executed_price": price,
                    "requested_price": price,
                    "fee": 0,
                    "timestamp": timestamp + index,
                    "market_context": {"price": price},
                    "trade_id": "boundary_" + side,
                }
                conn.execute("INSERT INTO paper_fills VALUES(?,?)", ("preview", json.dumps(fill)))
            conn.execute(
                "INSERT INTO trading_marks VALUES(?,?,?)",
                ("preview", 0, json.dumps({**context, "timestamp": timestamp + 1})),
            )

        for key, label, required_reason, previous_day in (
            ("max_daily_loss", "Daily loss threshold blocks new buys", "daily_loss_limit", False),
            ("max_drawdown", "Drawdown threshold blocks new buys", "drawdown_limit", True),
        ):
            threshold = rules[key]
            if threshold >= 100:
                rows.append(
                    {
                        "name": label,
                        "passed": False,
                        "skipped": True,
                        "decision": "not_applicable",
                        "reason": "A 100% loss leaves no cash for another buy; this branch is not reachable in a long-only unleveraged portfolio",
                        "expected": [],
                        "input": {"threshold_pct": threshold},
                    }
                )
                continue
            loss = (threshold + 100) / 2
            ledger_loss(loss, previous_day)
            remaining = value["starting_capital"] * (1 - loss / 100)
            candidate = {**order, "quantity": min(amount, remaining / 10) / context["price"] / slip}
            check(label, candidate, {"deny"})
            rows[-1]["passed"] = rows[-1]["passed"] and rows[-1]["reason"] == required_reason
            rows[-1]["input"].update(realized_test_loss_pct=loss, loss_recorded_previous_day=previous_day)
        conn.execute("DELETE FROM paper_fills")
        conn.execute("DELETE FROM trading_marks")

        # A pending order reserves the entire position allowance; a new buy must fail.
        reservation = {"params": {"side": "BUY", "quantity": rules["max_position_size"] / context["price"]}}
        conn.execute(
            "INSERT INTO trading_intents VALUES(?,?,?,?)",
            ("preview", "AWAITING_APPROVAL", "reserved", json.dumps(reservation)),
        )
        check("Pending orders reserve position capacity", order, {"deny"})
        rows[-1]["passed"] = rows[-1]["passed"] and rows[-1]["reason"] == "max_position_size"
        conn.execute("DELETE FROM trading_intents")
        conn.execute("UPDATE agents SET active=0")
        check("Stopped agent cannot execute", order, {"deny"})
        return rows
    finally:
        conn.close()


class PlanService:
    def __init__(self, strategies):
        self.s = strategies
        self.db = strategies.db

    def get(self, plan_id, owner_id, conn=None):
        if conn is None:
            with self.db.connect() as c:
                return self.get(plan_id, owner_id, c)
        row = conn.execute(
            "SELECT * FROM agent_plans WHERE plan_id=? AND owner_id=?", (plan_id, owner_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Agent plan not found")
        return {
            **dict(row),
            "configuration": json.loads(row["configuration"]),
            "report": json.loads(row["report"]),
        }

    def test(self, payload, owner_id):
        value = payload.model_dump()
        if payload.source_strategy_id:
            try:
                self.s.detail(payload.source_strategy_id, owner_id, payload.source_version)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                self.s.detail(payload.source_strategy_id, version=payload.source_version, public=True)
        if not self.s.settings.execution_enabled:
            raise HTTPException(409, "Platform execution is disabled")
        window = self.s.market_data.window(value["market"], value["timeframe"], 384)
        checks = policy_checks(self.s, value, window["bars"][-1])
        replay = self.s.market_data.slice(window, 288, 96)
        simulations = []
        for index in range(3):
            historical = self.s.market_data.slice(window, index * 96, 96)
            dataset = "Historical period " + str(index + 1)
            bars = historical["bars"]
            result = run_backtest(
                {**value, "agent_id": "preview", "strategy_id": "preview", "version": 1}, bars
            )
            simulations.append({"dataset": dataset, "market_data": provenance(historical), **result})
        report = {
            "checks": checks,
            "passed": sum(c["passed"] for c in checks),
            "total": sum(not c.get("skipped", False) for c in checks),
            "not_applicable": sum(c.get("skipped", False) for c in checks),
            "simulations": simulations,
            "ready": all(c["passed"] or c.get("skipped") for c in checks),
            "market_data": provenance(window),
            "replay_snapshot_id": replay["snapshot_id"],
            "replay_market_data": provenance(replay),
            "note": "Backtests use recorded Binance candles, with configured fees and slippage. Guardrails are checked separately. The final 96 candles are reserved for a separate paper replay. Results are not a profitability or maximum-loss guarantee.",
        }
        plan_id, now = "plan_" + uuid4().hex, int(time.time())
        review_hash = digest({"configuration": value, "report": report})
        with self.db.connect(write=True) as conn:
            count = conn.execute(
                "SELECT count(*) FROM agent_plans WHERE owner_id=? AND created_at>?", (owner_id, now - 86400)
            ).fetchone()[0]
            if count >= 100:
                raise HTTPException(429, "Daily plan test limit reached")
            conn.execute(
                "INSERT INTO agent_plans VALUES(?,?,?,?,?,?,NULL,NULL)",
                (plan_id, owner_id, json.dumps(value), json.dumps(report), review_hash, now),
            )
        return self.get(plan_id, owner_id)

    def deploy(self, plan_id, owner_id, payload):
        if not payload.acknowledged:
            raise HTTPException(422, "Review and acknowledge the deployment before continuing")
        with self.db.connect(write=True) as conn:
            plan = self.get(plan_id, owner_id, conn)
            if plan["review_hash"] != payload.reviewed_hash:
                raise HTTPException(409, "The reviewed configuration does not match the tested plan")
            if plan["strategy_id"]:
                return {"agent_id": plan["agent_id"], "strategy_id": plan["strategy_id"]}
            if not plan["report"]["ready"] or not self.s.settings.execution_enabled:
                raise HTTPException(409, "A passing test and enabled execution are required")
            for table, limit in (("agents", 50), ("strategies", 100)):
                if (
                    conn.execute(f"SELECT count(*) FROM {table} WHERE owner_id=?", (owner_id,)).fetchone()[0]
                    >= limit
                ):
                    raise HTTPException(409, "Workspace limit reached")
            snapshot_id = plan["report"].get("replay_snapshot_id")
            if not snapshot_id:
                raise HTTPException(409, "Run a new plan test on real market data before deploying")
            self.s.market_data.get(snapshot_id)
            value = AgentPlan.model_validate(plan["configuration"]).model_dump()
            now, aid, sid, dep, tid = (
                int(time.time()),
                "agent_" + uuid4().hex,
                "strategy_" + uuid4().hex,
                "deploy_" + uuid4().hex,
                "test_" + uuid4().hex,
            )
            key = Ed25519PrivateKey.generate()
            # This identity grants only the hosted paper runner; legacy transfers and connectors deny all.
            legacy = json.dumps(
                {
                    "allowed_actions": [],
                    "allowed_recipients": [self.s.control.actions.gateway.sender],
                    "max_transfer_sol": 0.000000001,
                    "daily_budget_sol": 0.000000001,
                }
            )
            conn.execute(
                "INSERT INTO agents(agent_id,name,public_key,created_at,policy,owner_id,description) VALUES(?,?,?,?,?,?,?)",
                (aid, value["name"], public_key(key), now, legacy, owner_id, value["goal"]),
            )
            conn.execute("INSERT INTO policy_versions VALUES(?,?,?,?,?)", (aid, 1, legacy, now, owner_id))
            denied = json.dumps(Policy(rules=[]).model_dump())
            conn.execute("INSERT INTO control_policies VALUES(?,?,?,?)", (aid, 1, denied, now))
            conn.execute("INSERT INTO control_policy_versions VALUES(?,?,?,?)", (aid, 1, denied, now))
            version = {k: value[k] for k in VersionInput.model_fields}
            conn.execute(
                "INSERT INTO strategies VALUES(?,?,?,?,?,1,'LIVE',0,?,?)",
                (sid, owner_id, aid, value["name"], value["goal"], now, now),
            )
            conn.execute("INSERT INTO strategy_versions VALUES(?,?,?,?)", (sid, 1, json.dumps(version), now))
            for index, simulation in enumerate(plan["report"]["simulations"]):
                run_id = tid if index == 0 else "test_" + uuid4().hex
                baseline = deepcopy(simulation)
                for fill in baseline["trades"]:
                    fill.update(agent_id=aid, strategy_id=sid)
                baseline.update(
                    test_id=run_id,
                    strategy_id=sid,
                    strategy_version=1,
                    starting_capital=value["starting_capital"],
                    market_period_start=baseline["market_context"][0]["timestamp"],
                    market_period_end=baseline["market_context"][-1]["timestamp"],
                    started_at=plan["created_at"],
                    finished_at=plan["created_at"],
                    strategy_snapshot=version,
                    plan_id=plan_id,
                    replay_snapshot_id=snapshot_id,
                    replay_market_data=plan["report"]["replay_market_data"],
                )
                baseline["result_hash"] = digest(baseline)
                baseline["public_key"] = self.s.receipts.public_key
                baseline["signature"] = sign(self.s.receipts.key, bytes.fromhex(baseline["result_hash"]))
                conn.execute(
                    "INSERT INTO strategy_tests VALUES(?,?,?,?,?,?)",
                    (run_id, sid, 1, plan["created_at"], plan["created_at"], json.dumps(baseline)),
                )
            conn.execute(
                "INSERT INTO trading_deployments VALUES(?,?,?,'LIVE',0,?,?,?,?)",
                (dep, sid, 1, now, tid, encode_base64(key.private_bytes_raw()), public_key(key)),
            )
            conn.execute("INSERT INTO deployment_market_data VALUES(?,?)", (dep, snapshot_id))
            self.s.control.event(
                conn,
                aid,
                "agent_plan_deployed",
                {
                    "plan_id": plan_id,
                    "review_hash": plan["review_hash"],
                    "intent": value,
                    "strategy_id": sid,
                    "deployment_id": dep,
                    "baseline_test_id": tid,
                    "mode": "paper",
                    "actor": owner_id,
                },
            )
            record_event(conn, owner_id, "agent_created", aid)
            conn.execute(
                "UPDATE agent_plans SET agent_id=?,strategy_id=? WHERE plan_id=?", (aid, sid, plan_id)
            )
        return {"agent_id": aid, "strategy_id": sid}


def plan_router(strategies, owner):
    service = PlanService(strategies)
    router = APIRouter(prefix="/v1/agent-plans", tags=["Agent onboarding"])

    @router.post("", status_code=201)
    def test(payload: AgentPlan, user=Depends(owner)):
        return service.test(payload, user["user_id"])

    @router.get("/{plan_id}")
    def get(plan_id: str, user=Depends(owner)):
        return service.get(plan_id, user["user_id"])

    @router.get("/{plan_id}/market-data")
    def market_data(plan_id: str, user=Depends(owner)):
        plan = service.get(plan_id, user["user_id"])
        return strategies.market_data.get(plan["report"]["market_data"]["snapshot_id"])

    @router.post("/{plan_id}/deploy")
    def deploy(plan_id: str, payload: PlanDeployment, user=Depends(owner)):
        return service.deploy(plan_id, user["user_id"], payload)

    return router
