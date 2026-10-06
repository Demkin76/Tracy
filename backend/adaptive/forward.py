"""24-hour forward paper comparison using public live quotes, never exchange orders."""

import asyncio
import json
import math
import time
from copy import deepcopy
from uuid import uuid4

import httpx
from fastapi import HTTPException

from backend.adaptive.engine import new_account, step
from backend.crypto.hashing import digest
from backend.execution_control import require_execution
from backend.market_data.provider import MARKETS, SECONDS, provenance
from backend.performance.metrics import calculate


class ForwardPaper:
    def __init__(self, adaptive):
        self.a, self.db = adaptive, adaptive.db

    def quote(self, market):
        began = time.time()
        try:
            with httpx.Client(timeout=10, trust_env=False) as client:
                r = client.get(
                    "https://data-api.binance.vision/api/v3/ticker/bookTicker",
                    params={"symbol": MARKETS[market]},
                )
                r.raise_for_status()
                item = r.json()
            bid, ask = float(item["bidPrice"]), float(item["askPrice"])
            bid_qty, ask_qty = float(item["bidQty"]), float(item["askQty"])
            if (
                not all(math.isfinite(v) and v > 0 for v in (bid, ask, bid_qty, ask_qty))
                or bid > ask
                or (ask / bid - 1) * 10000 > 50
                or time.time() - began > 5
            ):
                raise ValueError("Invalid, wide-spread or delayed quote")
            return {
                "bid": bid,
                "ask": ask,
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
                "price": (bid + ask) / 2,
                "timestamp": int(time.time()),
                "source": "Binance Spot bookTicker",
                "roundtrip_ms": round((time.time() - began) * 1000),
                "time_basis": "Local receipt time; REST quote does not contain exchange event time",
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                503, "Live bid/ask unavailable or stale. No substitute quotes or orders were generated."
            ) from exc

    def get(self, fid, owner_id):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM adaptive_forward WHERE forward_id=? AND owner_id=?", (fid, owner_id)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Forward experiment not found")
            body = json.loads(row["body"])
            events = conn.execute(
                "SELECT body FROM adaptive_forward_events WHERE forward_id=? ORDER BY sequence", (fid,)
            ).fetchall()
        body.update(
            status=row["status"], forward_id=fid, agent_id=row["agent_id"], next_tick=row["next_tick"]
        )
        body["events"] = [json.loads(r[0]) for r in events]
        previous = None
        for event in body["events"]:
            value = self.a.checked(event)
            if value["previous_hash"] != previous:
                raise HTTPException(409, "Forward event chain invalid")
            previous = event["hash"]
        body["proof_valid"] = (
            bool(events)
            and body["events"][-1]["body"]["state_hash"] == digest(json.loads(row["body"]))
            and body["events"][-1]["body"]["status"] == row["status"]
        )
        if not body["proof_valid"]:
            raise HTTPException(409, "Forward state does not match signed event chain")
        body["baseline_metrics"] = calculate(
            body["baseline"]["fills"], body["blueprint"]["capital"], body["baseline"]["marks"]
        )
        body["agent_metrics"] = calculate(
            body["agent"]["fills"], body["blueprint"]["capital"], body["agent"]["marks"]
        )
        return body

    def save(self, conn, fid, status, due, body, event):
        prior = conn.execute(
            "SELECT sequence,body FROM adaptive_forward_events WHERE forward_id=? ORDER BY sequence DESC LIMIT 1",
            (fid,),
        ).fetchone()
        sequence = prior[0] + 1 if prior else 1
        receipt = self.a.signed(
            {
                "forward_id": fid,
                "sequence": sequence,
                "previous_hash": json.loads(prior[1])["hash"] if prior else None,
                "state_hash": digest(body),
                "status": status,
                "timestamp": int(time.time()),
                "event": event,
            }
        )
        conn.execute(
            "UPDATE adaptive_forward SET status=?,next_tick=?,body=? WHERE forward_id=?",
            (status, due, json.dumps(body), fid),
        )
        conn.execute(
            "INSERT INTO adaptive_forward_events VALUES(?,?,?)", (fid, sequence, json.dumps(receipt))
        )

    def start(self, aid, owner_id, revision):
        require_execution(self.a.s.settings)
        agent = self.a.get(aid, owner_id)
        if agent["revision"] != revision or not agent["review_report"]:
            raise HTTPException(409, "Run and review a historical experiment before forward paper")
        with self.db.connect() as conn:
            reviewed = conn.execute(
                "SELECT body FROM adaptive_reviews WHERE agent_id=? AND revision=?", (aid, revision)
            ).fetchone()
        if not reviewed:
            raise HTTPException(409, "Explicitly review this revision and learning mode before starting")
        review = self.a.checked(json.loads(reviewed[0]))
        if (
            review["state_hash"] != digest(agent["state"])
            or review["strategy_hash"] != agent["strategy_hash"]
        ):
            raise HTTPException(409, "Start review no longer matches this policy")
        bp = agent["strategy_apr"]["blueprint"]
        bars = self.a.s.market_data.window(
            bp["market"], bp["timeframe"], max(bp["program"]["slow"] + 1, bp["program"]["lookback"])
        )
        quote = self.quote(bp["market"])
        now, interval = int(time.time()), SECONDS[bp["timeframe"]]
        fid = "forward_" + uuid4().hex
        body = {
            "blueprint": bp,
            "policy_mode": review["policy_mode"],
            "start_review": digest(review),
            "strategy_hash": agent["strategy_hash"],
            "revision": revision,
            "state": deepcopy(agent["state"]),
            "baseline": new_account(),
            "agent": new_account(),
            "started_at": now,
            "ends_at": now + 86400,
            "last_candle": bars["period_end"],
            "last_quote": quote,
            "observations": 0,
            "last_error": None,
            "execution": "Forward paper at observed bid/ask plus fees and slippage; no exchange orders. Learning counts update on closed outcomes; active policy remains frozen during this comparison.",
        }
        with self.db.connect(write=True) as conn:
            require_execution(self.a.s.settings)
            if self.a.get(aid, owner_id, conn)["revision"] != revision:
                raise HTTPException(409, "Agent changed while checking data")
            if conn.execute(
                "SELECT 1 FROM adaptive_forward WHERE agent_id=? AND status IN ('RUNNING','STOPPING')", (aid,)
            ).fetchone():
                raise HTTPException(409, "A forward experiment is already active")
            conn.execute(
                "INSERT INTO adaptive_forward VALUES(?,?,?,'RUNNING',?,?)",
                (fid, aid, owner_id, bars["period_end"] + interval + 3, json.dumps(body)),
            )
            self.save(
                conn,
                fid,
                "RUNNING",
                bars["period_end"] + interval + 3,
                body,
                {"kind": "started", "warmup": provenance(bars)},
            )
        return self.get(fid, owner_id)

    def stop(self, fid, owner_id):
        self.get(fid, owner_id)
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT status,body FROM adaptive_forward WHERE forward_id=?", (fid,)
            ).fetchone()
            if row[0] not in ("RUNNING", "STOPPING"):
                return self.get(fid, owner_id)
            body = json.loads(row[1])
            body["stop_reason"] = "Owner requested closing both paper portfolios"
            self.save(conn, fid, "STOPPING", int(time.time()), body, {"kind": "stop_requested"})
        return self.get(fid, owner_id)

    def advance(self, fid, owner_id):
        require_execution(self.a.s.settings)
        original = self.get(fid, owner_id)
        if original["status"] not in ("RUNNING", "STOPPING"):
            return original
        bp = original["blueprint"]
        end = original["status"] == "STOPPING" or time.time() >= original["ends_at"]
        history = self.a.s.market_data.window(
            bp["market"], bp["timeframe"], max(bp["program"]["slow"] + 1, bp["program"]["lookback"])
        )
        if not end and history["period_end"] <= original["last_candle"]:
            return original
        quote = self.quote(bp["market"])
        gap = not end and (
            history["period_end"] > original["last_candle"] + SECONDS[bp["timeframe"]]
            or quote["timestamp"] - history["period_end"] > 120
        )
        # Never catch up old decisions at old prices. Close at the current quote.
        end = end or gap
        with self.db.connect(write=True) as conn:
            require_execution(self.a.s.settings)
            row = conn.execute(
                "SELECT status,body FROM adaptive_forward WHERE forward_id=? AND owner_id=?", (fid, owner_id)
            ).fetchone()
            body = json.loads(row[1])
            if row[0] != original["status"] or body["observations"] != original["observations"]:
                raise HTTPException(409, "Forward run advanced concurrently; reload")
            if body.get("policy_mode") == "adaptive":
                current = self.a.get(original["agent_id"], owner_id, conn)
                if current["revision"] != body["revision"]:
                    # Preserve execution statistics accrued since the last policy revision.
                    updated = deepcopy(current["state"])
                    for old_arm, new_arm in zip(body["state"]["arms"], updated["arms"]):
                        for key in ("closed_trades", "net_pnl"):
                            new_arm[key] = old_arm[key]
                    body["state"] = updated
                    body["revision"] = current["revision"]
            baseline_state = deepcopy(body["state"])
            # Original baseline must not inherit learned entry admission probabilities.
            if baseline_state.get("apr"):
                for rule in baseline_state["apr"]:
                    rule["probability"] = 0.5
            for label, arm, learning in (
                ("baseline", 0, False),
                ("agent", body["state"]["active_arm"], True),
            ):
                account = body[label]
                prior_fill_count = len(account["fills"])
                # Current quote marks existing inventory before a risk decision.
                account["marks"].append(quote)
                step(
                    bp,
                    account,
                    body["state"] if learning else baseline_state,
                    history["bars"],
                    quote,
                    body["observations"],
                    arm,
                    learning,
                    force_exit=end,
                    bid=quote["bid"],
                    ask=quote["ask"],
                    quote_sizes={"BUY": quote["ask_qty"], "SELL": quote["bid_qty"]},
                )
                if learning and len(account["fills"]) > prior_fill_count:
                    self.a.learning.record(
                        conn,
                        fid,
                        original["agent_id"],
                        owner_id,
                        bp,
                        body["state"],
                        body["revision"],
                        account["decisions"][-1],
                        account["fills"][-1],
                        history["bars"],
                    )
            body.update(
                last_candle=history["period_end"],
                last_quote=quote,
                observations=body["observations"] + 1,
                last_error=None,
            )
            status = "COMPLETED" if end else "RUNNING"
            if gap:
                body["stop_reason"] = (
                    "Data gap or scheduler delay: closed using current quote, no historical fill replay"
                )
            if end:
                current = self.a.get(original["agent_id"], owner_id, conn)
                # Policy is unchanged. Only this agent's new, net closed outcomes transfer.
                if current["revision"] != body["revision"]:
                    raise HTTPException(409, "Agent revision changed during forward experiment")
                state = body["state"]
                state["observed_until"] = max(state["observed_until"], quote["timestamp"])
                state["personal_closed_trades"] = (
                    current["state"].get("personal_closed_trades", 0)
                    + calculate(body["agent"]["fills"], bp["capital"], body["agent"]["marks"])[
                        "closed_trade_count"
                    ]
                )
                self.a.save_state(conn, current["agent_id"], current["revision"] + 1, state)
                conn.execute(
                    "UPDATE adaptive_agents SET revision=revision+1 WHERE agent_id=?", (current["agent_id"],)
                )
                body["completed_at"] = quote["timestamp"]
            event = {
                "kind": "closed" if end else "observation",
                "quote": quote,
                "market_data": provenance(history),
                "agent_decision": body["agent"]["decisions"][-1],
                "baseline_decision": body["baseline"]["decisions"][-1],
            }
            due = min(history["period_end"] + SECONDS[bp["timeframe"]] + 3, body["ends_at"])
            self.save(conn, fid, status, due, body, event)
            if end:
                self.a.learning.feedback(conn, original["agent_id"], owner_id)
        return self.get(fid, owner_id)

    async def tick(self):
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT forward_id,owner_id FROM adaptive_forward WHERE status IN ('RUNNING','STOPPING') AND next_tick<=? LIMIT 5",
                (int(time.time()),),
            ).fetchall()
        for fid, owner_id in rows:
            try:
                await asyncio.to_thread(self.advance, fid, owner_id)
            except Exception as exc:
                with self.db.connect(write=True) as conn:
                    row = conn.execute(
                        "SELECT body,status FROM adaptive_forward WHERE forward_id=?", (fid,)
                    ).fetchone()
                    if row[1] not in ("RUNNING", "STOPPING"):
                        continue
                    body = json.loads(row[0])
                    body["last_error"] = (
                        exc.detail
                        if isinstance(exc, HTTPException)
                        else "Quote or execution check failed; retry pending"
                    )
                    self.save(
                        conn,
                        fid,
                        row[1],
                        int(time.time()) + 60,
                        body,
                        {"kind": "retry", "reason": body["last_error"]},
                    )
