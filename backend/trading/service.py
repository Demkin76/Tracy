import json
import time
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from backend.crypto.hashing import canonical_bytes, digest
from backend.crypto.signatures import private_key, sign
from backend.performance.metrics import calculate
from backend.trading.adapters import PaperAdapter, signal
from backend.trading.models import Order


class TradingService:
    def __init__(self, strategies):
        self.s = strategies
        self.db = strategies.db

    def crypto_valid(self, proof):
        from backend.trading.verify import valid_receipt

        return valid_receipt(proof, self.s.receipts.public_key)

    def bars(self, strategy, deployment):
        with self.db.connect() as conn:
            row = conn.execute("SELECT snapshot_id FROM deployment_market_data WHERE deployment_id=?", (deployment["deployment_id"],)).fetchone()
        if not row:
            raise HTTPException(409, "This legacy demo has no recorded exchange data. Create and test a new version.")
        snapshot = self.s.market_data.get(row[0])
        return [{**bar, "snapshot_id": snapshot["snapshot_id"]} for bar in snapshot["bars"]]

    def ledger(self, conn, deployment):
        fills = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT body FROM paper_fills WHERE deployment_id=? ORDER BY rowid",
                (deployment["deployment_id"],),
            )
        ]
        marks = [
            json.loads(r[0])
            for r in conn.execute(
                "SELECT body FROM trading_marks WHERE deployment_id=? ORDER BY step",
                (deployment["deployment_id"],),
            )
        ]
        return fills, marks

    def evaluate(self, conn, strategy, deployment, order, context, exclude_intent=None):
        agent = conn.execute(
            "SELECT active,status_version FROM agents WHERE agent_id=?", (strategy["agent_id"],)
        ).fetchone()
        reason = None
        if not self.s.settings.execution_enabled:
            reason = "platform_execution_disabled"
        elif not agent["active"]:
            reason = "agent_stopped"
        elif (
            strategy["version"] != order["strategy_version"]
            or deployment["strategy_version"] != strategy["version"]
        ):
            reason = "strategy_version_changed"
        elif strategy["status"] not in ("LIVE", "DEGRADED") or deployment["status"] != "LIVE":
            reason = "strategy_not_live"
        elif deployment["step"] >= 96 and exclude_intent is None:
            reason = "replay_finished"
        fills, marks = self.ledger(conn, deployment)
        portfolio = calculate(fills, strategy["starting_capital"], marks + [context])
        rules = strategy["guardrails"]
        pending = conn.execute(
            "SELECT request FROM trading_intents WHERE deployment_id=? AND status='AWAITING_APPROVAL' AND intent_id!=?",
            (deployment["deployment_id"], exclude_intent or ""),
        ).fetchall()
        reserved_buy = reserved_sell = 0.0
        for row in pending:
            p = json.loads(row[0])["params"]
            if p["side"] == "BUY":
                reserved_buy += (
                    p["quantity"]
                    * context["price"]
                    * (1 + strategy["strategy_config"]["slippage_bps"] / 10000)
                    * (1 + strategy["strategy_config"]["fee_bps"] / 10000)
                )
            else:
                reserved_sell += p["quantity"]
        fill_price = context["price"] * (
            1 + strategy["strategy_config"]["slippage_bps"] / 10000
            if order["side"] == "BUY"
            else 1 - strategy["strategy_config"]["slippage_bps"] / 10000
        )
        notional = order["quantity"] * fill_price
        day_start = context["timestamp"] // 86400 * 86400
        earlier = [
            p["equity"]
            for p in portfolio["equity_curve"]
            if p["timestamp"] is not None and p["timestamp"] < day_start
        ]
        day_open = earlier[-1] if earlier else strategy["starting_capital"]
        daily_loss = max(0, (day_open - portfolio["equity"]) / day_open * 100)
        if reason is None:
            if strategy["market"] not in rules["allowed_markets"] or not set(strategy["symbols"]) <= set(
                rules["allowed_tokens"]
            ):
                reason = "market_or_token_not_allowed"
            elif notional > rules["max_trade_size"]:
                reason = "max_trade_size"
            elif abs(fill_price / order["requested_price"] - 1) * 10000 > order["max_slippage_bps"]:
                reason = "slippage_limit"
            elif order["side"] == "BUY":
                if portfolio["position_value"] + reserved_buy + notional > rules["max_position_size"]:
                    reason = "max_position_size"
                elif (
                    notional * (1 + strategy["strategy_config"]["fee_bps"] / 10000)
                    > portfolio["cash"] - reserved_buy + 0.000001
                ):
                    reason = "insufficient_cash"
                elif daily_loss >= rules["max_daily_loss"]:
                    reason = "daily_loss_limit"
                elif portfolio["max_drawdown"] >= rules["max_drawdown"]:
                    reason = "drawdown_limit"
                elif (1 if portfolio["position_quantity"] or reserved_buy else 0) + (
                    0 if portfolio["position_quantity"] or reserved_buy else 1
                ) > rules["max_open_positions"]:
                    reason = "max_open_positions"
            elif order["quantity"] > portfolio["position_quantity"] - reserved_sell + 0.00000001:
                reason = "insufficient_position"
        snapshot = {
            "market_context": context,
            "portfolio": {
                k: v for k, v in portfolio.items() if k not in ("equity_curve", "realized_by_trade")
            },
            "daily_loss_pct": daily_loss,
            "reserved_buy": reserved_buy,
            "reserved_sell": reserved_sell,
            "agent_status_version": agent["status_version"],
            "notional": notional,
        }
        return (
            ("deny", reason, snapshot)
            if reason
            else (
                "review" if notional > rules["human_approval_above"] else "allow",
                "human_approval_required" if notional > rules["human_approval_above"] else "allowed",
                snapshot,
            )
        )

    def quote(self, request):
        agent = self.s.control.authenticate_agent(
            request.agent_id, request.timestamp, request.signature, request.model_dump(exclude={"signature"})
        )
        with self.db.connect() as conn:
            strategy = self.s.get(request.strategy_id, agent["owner_id"], conn=conn)
            if strategy["agent_id"] != request.agent_id:
                raise HTTPException(403, "Agent is not assigned to this strategy")
            row = conn.execute(
                "SELECT * FROM trading_deployments WHERE deployment_id=? AND strategy_id=? AND strategy_version=?",
                (request.task_id, strategy["strategy_id"], strategy["version"]),
            ).fetchone()
            if not row:
                raise HTTPException(403, "No current owner-granted deployment")
            deployment = dict(row)
            context = self.bars(strategy, deployment)[max(0, min(95, deployment["step"] - 1))]
            return {
                "strategy_id": strategy["strategy_id"],
                "strategy_version": strategy["version"],
                "market": strategy["market"],
                "mode": "paper",
                "context": context,
                "replay_step": deployment["step"],
                "status": strategy["status"],
            }

    def submit(self, request):
        agent = self.s.control.authenticate_agent(
            request.agent_id, request.timestamp, request.signature, request.unsigned()
        )
        if request.action != "trading.order":
            raise HTTPException(422, "Expected trading.order")
        try:
            order = Order.model_validate(request.params).model_dump()
        except ValidationError:
            raise HTTPException(422, "Invalid trading order parameters")
        with self.db.connect(write=True) as conn:
            strategy = self.s.get(request.resource_id, agent["owner_id"], conn=conn)
            if strategy["agent_id"] != request.agent_id:
                raise HTTPException(403, "Agent does not own this strategy")
            deployment = conn.execute(
                "SELECT * FROM trading_deployments WHERE deployment_id=? AND strategy_id=?",
                (request.task_id, strategy["strategy_id"]),
            ).fetchone()
            if not deployment:
                raise HTTPException(403, "Owner must deploy and grant this strategy task")
            deployment = dict(deployment)
            context = self.bars(strategy, deployment)[max(0, min(95, deployment["step"] - 1))]
            item = self.admit(
                conn, strategy, deployment, request.model_dump(), order, context, "agent", agent["public_key"]
            )
            snapshot = self.s.performance.snapshot(conn, strategy)
            self.s.degradation.evaluate(conn, strategy, snapshot, record=True)
        return self.get(item, agent_id=request.agent_id)

    def admit(self, conn, strategy, deployment, request, order, context, source, decision_key):
        previous = conn.execute(
            "SELECT intent_id,request FROM trading_intents WHERE agent_id=? AND request_id=?",
            (request["agent_id"], request["request_id"]),
        ).fetchone()
        if previous:

            def semantic(r):
                return {k: v for k, v in r.items() if k not in ("timestamp", "signature")}

            if semantic(json.loads(previous["request"])) != semantic(request):
                raise HTTPException(409, "Request ID already used for another intent")
            return previous["intent_id"]
        choice, reason, evaluation = self.evaluate(conn, strategy, deployment, order, context)
        intent_id = "tintent_" + uuid4().hex
        intent_hash = digest({k: v for k, v in request.items() if k != "signature"})
        decision = {
            "source": source,
            "public_key": decision_key,
            "context": evaluation,
            "owner_grant": deployment["deployment_id"],
        }
        status = "REJECTED" if choice == "deny" else "AWAITING_APPROVAL" if choice == "review" else "QUEUED"
        now = int(time.time())
        conn.execute(
            "INSERT INTO trading_intents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (
                intent_id,
                deployment["deployment_id"],
                request["agent_id"],
                request["request_id"],
                intent_hash,
                json.dumps(request),
                json.dumps(decision),
                json.dumps(strategy["guardrails"]),
                status,
                reason,
                now,
                now + 900,
            ),
        )
        self.s.control.event(
            conn,
            strategy["agent_id"],
            "trading_intent_received",
            {
                "intent_id": intent_id,
                "intent_hash": intent_hash,
                "request": request,
                "decision": decision,
                "status": status,
                "strategy_id": strategy["strategy_id"],
                "version": strategy["version"],
                "guardrails": strategy["guardrails"],
            },
        )
        if choice == "deny":
            self.s.degradation.alert(
                conn, strategy, "risk_limit_reached", "WATCH", "Trading intent rejected: " + reason
            )
        elif choice == "allow":
            self.execute(conn, intent_id, strategy, deployment, order, context)
        return intent_id

    def execute(self, conn, intent_id, strategy, deployment, order, context):
        row = dict(conn.execute("SELECT * FROM trading_intents WHERE intent_id=?", (intent_id,)).fetchone())
        choice, reason, evaluation = self.evaluate(conn, strategy, deployment, order, context, intent_id)
        old = json.loads(row["decision"])
        if old["context"]["agent_status_version"] != evaluation["agent_status_version"]:
            choice, reason = "deny", "agent_status_changed"
        if row["approval_expires_at"] <= int(time.time()):
            choice, reason = "deny", "intent_expired"
        if choice == "review" and not row["approval"]:
            return
        if choice == "deny":
            conn.execute(
                "UPDATE trading_intents SET status='REJECTED',reason=? WHERE intent_id=?", (reason, intent_id)
            )
            self.s.control.event(
                conn,
                strategy["agent_id"],
                "trading_intent_rejected",
                {"intent_id": intent_id, "reason": reason},
            )
            self.s.degradation.alert(
                conn, strategy, "risk_limit_reached", "WATCH", "Trading intent rejected: " + reason
            )
            return
        trade_id = "trade_" + uuid4().hex
        fill = PaperAdapter.execute(
            order,
            context,
            strategy["strategy_config"],
            trade_id,
            intent_id,
            strategy,
            deployment["deployment_id"],
        )
        fill["executed_at"] = int(time.time())
        conn.execute(
            "INSERT INTO paper_fills VALUES(?,?,?,?)",
            (trade_id, intent_id, deployment["deployment_id"], json.dumps(fill)),
        )
        if not PaperAdapter.verify(conn, fill):
            raise RuntimeError("Paper ledger readback failed")
        fills, marks = self.ledger(conn, deployment)
        metrics = calculate(fills, strategy["starting_capital"], marks + [context])
        head = conn.execute(
            "SELECT sequence,receipt_hash FROM trading_receipts WHERE strategy_id=? ORDER BY sequence DESC LIMIT 1",
            (strategy["strategy_id"],),
        ).fetchone()
        proof = {
            "schema_version": "tracy.trading-receipt/3",
            "trade_id": trade_id,
            "strategy_id": strategy["strategy_id"],
            "strategy_version": strategy["version"],
            "strategy_snapshot": {
                k: strategy[k]
                for k in (
                    "market",
                    "symbols",
                    "timeframe",
                    "starting_capital",
                    "strategy_config",
                    "guardrails",
                )
            },
            "agent_id": strategy["agent_id"],
            "intent": json.loads(row["request"]),
            "intent_hash": row["intent_hash"],
            "decision_source": old["source"],
            "decision_public_key": old["public_key"],
            "owner_grant": old["owner_grant"],
            "policy": {"allowed": True, "snapshot": json.loads(row["policy"]), "context": evaluation},
            "approval": json.loads(row["approval"]) if row["approval"] else None,
            "trade": fill,
            "execution": {
                "mode": "paper",
                "on_chain": False,
                "tx_signature": None,
                "readback": "paper_ledger_matches",
            },
            "outcome": {
                "equity": metrics["equity"],
                "pnl": metrics["pnl"],
                "realized_pnl": metrics["realized_by_trade"].get(trade_id),
                "note": "Portfolio marked at this fill; later outcomes are derived from the immutable ledger.",
            },
            "timestamp": int(time.time()),
            "sequence": head["sequence"] + 1 if head else 1,
            "previous_receipt_hash": head["receipt_hash"] if head else None,
            "public_key": self.s.receipts.public_key,
        }
        proof["receipt_hash"] = digest(proof)
        proof["signature"] = sign(self.s.receipts.key, bytes.fromhex(proof["receipt_hash"]))
        conn.execute(
            "INSERT INTO trading_receipts VALUES(?,?,?,?,?)",
            (trade_id, strategy["strategy_id"], proof["sequence"], proof["receipt_hash"], json.dumps(proof)),
        )
        conn.execute(
            "UPDATE trading_intents SET status='VERIFIED',reason='paper_ledger_matches' WHERE intent_id=?",
            (intent_id,),
        )
        self.s.control.event(
            conn,
            strategy["agent_id"],
            "trade_verified",
            {
                "intent_id": intent_id,
                "trade_id": trade_id,
                "receipt_hash": proof["receipt_hash"],
                "mode": "paper",
            },
        )

    def get(self, intent_id, owner_id=None, agent_id=None):
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT i.*,s.owner_id,s.strategy_id FROM trading_intents i JOIN trading_deployments d ON d.deployment_id=i.deployment_id
                JOIN strategies s ON s.strategy_id=d.strategy_id WHERE i.intent_id=?""",
                (intent_id,),
            ).fetchone()
            if (
                not row
                or (owner_id and row["owner_id"] != owner_id)
                or (agent_id and row["agent_id"] != agent_id)
            ):
                raise HTTPException(404, "Trading intent not found")
            item = dict(row)
            for key in ("request", "policy", "decision", "approval"):
                item[key] = json.loads(item[key]) if item[key] else None
            proof = conn.execute(
                "SELECT body FROM trading_receipts WHERE trade_id=(SELECT trade_id FROM paper_fills WHERE intent_id=?)",
                (intent_id,),
            ).fetchone()
            item["receipt"] = json.loads(proof[0]) if proof else None
            item["policy_version"] = item["request"]["params"]["strategy_version"]
            return item

    def decide(self, intent_id, owner_id, payload):
        current = self.get(intent_id, owner_id)
        with self.db.connect(write=True) as conn:
            row = dict(
                conn.execute("SELECT * FROM trading_intents WHERE intent_id=?", (intent_id,)).fetchone()
            )
            if row["status"] != "AWAITING_APPROVAL":
                raise HTTPException(409, "Intent no longer awaits approval")
            if (
                payload.intent_hash != row["intent_hash"]
                or payload.policy_version != current["policy_version"]
            ):
                raise HTTPException(409, "Approval does not match the exact intent/version")
            strategy = self.s.get(current["strategy_id"], owner_id, conn=conn)
            deployment = dict(
                conn.execute(
                    "SELECT * FROM trading_deployments WHERE deployment_id=?", (row["deployment_id"],)
                ).fetchone()
            )
            approval = {
                **payload.model_dump(),
                "actor": owner_id,
                "timestamp": int(time.time()),
                "expires_at": row["approval_expires_at"],
            }
            conn.execute(
                "UPDATE trading_intents SET approval=? WHERE intent_id=?", (json.dumps(approval), intent_id)
            )
            if payload.decision == "deny":
                conn.execute(
                    "UPDATE trading_intents SET status='REJECTED',reason='human_denied' WHERE intent_id=?",
                    (intent_id,),
                )
            else:
                context = self.bars(strategy, deployment)[max(0, min(95, deployment["step"] - 1))]
                self.execute(
                    conn,
                    intent_id,
                    strategy,
                    deployment,
                    Order.model_validate(current["request"]["params"]).model_dump(),
                    context,
                )
            self.s.control.event(
                conn,
                strategy["agent_id"],
                "trading_human_decision",
                {"intent_id": intent_id, "approval": approval},
            )
            snapshot = self.s.performance.snapshot(conn, strategy)
            self.s.degradation.evaluate(conn, strategy, snapshot, record=True)
        return self.get(intent_id, owner_id)

    def advance(self, strategy_id, owner_id, payload):
        with self.db.connect(write=True) as conn:
            strategy = self.s.get(strategy_id, owner_id, conn=conn)
            deployment = conn.execute(
                "SELECT * FROM trading_deployments WHERE strategy_id=? AND strategy_version=?",
                (strategy_id, strategy["version"]),
            ).fetchone()
            if not deployment:
                raise HTTPException(409, "Deploy this version first")
            deployment = dict(deployment)
            if deployment["step"] != payload.expected_step:
                raise HTTPException(409, "Replay already advanced; reload current step")
            if strategy["status"] not in ("LIVE", "DEGRADED") or deployment["status"] != "LIVE":
                raise HTTPException(409, "Strategy is not live")
            bars = self.bars(strategy, deployment)
            generated = []
            for step in range(deployment["step"], min(96, deployment["step"] + payload.steps)):
                # Resolve older approvals explicitly before advancing the market clock.
                if conn.execute(
                    "SELECT 1 FROM trading_intents WHERE deployment_id=? AND status='AWAITING_APPROVAL' LIMIT 1",
                    (deployment["deployment_id"],),
                ).fetchone():
                    break
                fills, marks = self.ledger(conn, deployment)
                portfolio = calculate(fills, strategy["starting_capital"], marks + [bars[step]])
                entry = max((f["market_context"]["bar"] for f in fills if f["side"] == "BUY"), default=-1)
                side = signal(strategy["strategy_config"], bars, step, portfolio["position_quantity"], entry)
                deployment["step"] = step
                if side:
                    config = strategy["strategy_config"]
                    quantity = (
                        portfolio["cash"]
                        * config["allocation_pct"]
                        / 100
                        / (
                            bars[step]["price"]
                            * (1 + config["slippage_bps"] / 10000)
                            * (1 + config["fee_bps"] / 10000)
                        )
                        if side == "BUY"
                        else portfolio["position_quantity"]
                    )
                    order = Order(
                        strategy_version=strategy["version"],
                        side=side,
                        quantity=round(quantity, 8),
                        requested_price=bars[step]["price"],
                    ).model_dump()
                    request = {
                        "schema_version": "tracy.intent/2",
                        "request_id": deployment["deployment_id"] + "_" + str(step),
                        "agent_id": strategy["agent_id"],
                        "task_id": deployment["deployment_id"],
                        "action": "trading.order",
                        "resource_id": strategy_id,
                        "params": order,
                        "reason": "Hosted deterministic paper runner decision",
                        "timestamp": int(time.time()),
                    }
                    request["signature"] = sign(
                        private_key(deployment["runner_seed"]), canonical_bytes(request)
                    )
                    generated.append(
                        self.admit(
                            conn,
                            strategy,
                            deployment,
                            request,
                            order,
                            bars[step],
                            "hosted_paper_runner",
                            deployment["runner_public_key"],
                        )
                    )
                conn.execute(
                    "INSERT INTO trading_marks VALUES(?,?,?)",
                    (deployment["deployment_id"], step, json.dumps(bars[step])),
                )
                deployment["step"] = step + 1
                conn.execute(
                    "UPDATE trading_deployments SET step=? WHERE deployment_id=?",
                    (step + 1, deployment["deployment_id"]),
                )
                snapshot = self.s.performance.snapshot(conn, strategy)
                health = self.s.degradation.evaluate(conn, strategy, snapshot, record=True)
                if health["status"] == "CRITICAL":
                    break
            self.s.control.event(
                conn,
                strategy["agent_id"],
                "paper_replay_advanced",
                {"strategy_id": strategy_id, "version": strategy["version"], "step": deployment["step"]},
            )
        return {"step": deployment["step"], "intent_ids": generated, "finished": deployment["step"] >= 96}

    def probe(self, strategy_id, owner_id):
        with self.db.connect(write=True) as conn:
            strategy = self.s.get(strategy_id, owner_id, conn=conn)
            row = conn.execute(
                "SELECT * FROM trading_deployments WHERE strategy_id=? AND strategy_version=?",
                (strategy_id, strategy["version"]),
            ).fetchone()
            if not row:
                raise HTTPException(409, "Deploy a paper strategy first")
            deployment = dict(row)
            context = self.bars(strategy, deployment)[max(0, min(95, deployment["step"] - 1))]
            order = Order(
                strategy_version=strategy["version"],
                side="BUY",
                quantity=round(strategy["guardrails"]["max_trade_size"] * 2 / context["price"], 8),
                requested_price=context["price"],
            ).model_dump()
            request = {
                "schema_version": "tracy.intent/2",
                "request_id": "probe_" + uuid4().hex,
                "agent_id": strategy["agent_id"],
                "task_id": deployment["deployment_id"],
                "action": "trading.order",
                "resource_id": strategy_id,
                "params": order,
                "reason": "Owner-requested oversized paper order to demonstrate risk enforcement",
                "timestamp": int(time.time()),
            }
            request["signature"] = sign(private_key(deployment["runner_seed"]), canonical_bytes(request))
            iid = self.admit(
                conn,
                strategy,
                deployment,
                request,
                order,
                context,
                "hosted_paper_runner",
                deployment["runner_public_key"],
            )
        return self.get(iid, owner_id)

    def proof(self, trade_id, owner_id=None, public=False):
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT r.body,s.owner_id,s.listed,a.listed AS agent_listed FROM trading_receipts r
                JOIN strategies s ON s.strategy_id=r.strategy_id JOIN agents a ON a.agent_id=s.agent_id WHERE r.trade_id=?""",
                (trade_id,),
            ).fetchone()
            if not row or (public and not row["listed"]) or (not public and row["owner_id"] != owner_id):
                raise HTTPException(404, "Trading proof not found")
            proof = json.loads(row["body"])
            chain = [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT body FROM trading_receipts WHERE strategy_id=? AND sequence<=? ORDER BY sequence",
                    (proof["strategy_id"], proof["sequence"]),
                )
            ]
            previous = None
            valid = True
            for n, p in enumerate(chain, 1):
                valid = (
                    valid
                    and self.crypto_valid(p)
                    and p["sequence"] == n
                    and p["previous_receipt_hash"] == previous
                )
                previous = p["receipt_hash"]
            readback = PaperAdapter.verify(conn, proof["trade"])
        context = proof["trade"]["market_context"]
        snapshot_id = context.get("snapshot_id")
        market_matches = None
        market_source = None
        if snapshot_id:
            snapshot = self.s.market_data.get(snapshot_id)
            bar = context.get("bar", -1)
            market_matches = 0 <= bar < len(snapshot["bars"]) and snapshot["bars"][bar] == {
                k: v for k, v in context.items() if k != "snapshot_id"
            }
            market_source = {k: v for k, v in snapshot.items() if k != "bars"}
        return {
            "receipt": proof,
            "chain": chain,
            "market_data": market_source,
            "checks": {
                "valid": bool(valid and readback and market_matches is not False),
                "market_data_matches": market_matches,
                "signature_valid": self.crypto_valid(proof),
                "chain_valid": bool(valid),
                "readback_matches": readback,
                "on_chain": False,
                "mode": "paper",
            },
        }

    async def tick(self):
        with self.db.connect(write=True) as conn:
            rows = conn.execute(
                """SELECT i.intent_id,i.agent_id FROM trading_intents i
                JOIN trading_deployments d ON d.deployment_id=i.deployment_id
                JOIN strategies s ON s.strategy_id=d.strategy_id JOIN agents a ON a.agent_id=i.agent_id
                WHERE i.status='AWAITING_APPROVAL' AND (i.approval_expires_at<=? OR s.version!=d.strategy_version OR s.status NOT IN ('LIVE','DEGRADED') OR a.active=0)""",
                (int(time.time()),),
            ).fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE trading_intents SET status='REJECTED',reason='approval_invalidated' WHERE intent_id=?",
                    (r["intent_id"],),
                )
                self.s.control.event(
                    conn, r["agent_id"], "trading_approval_invalidated", {"intent_id": r["intent_id"]}
                )
