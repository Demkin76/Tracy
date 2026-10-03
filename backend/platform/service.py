import csv
import io
import json
import math
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from backend.database.db import unpack_action
from backend.policies.engine import lamports, utc_day


def metrics(rows):
    counts = {s: 0 for s in ("VERIFIED", "REJECTED", "FAILED", "PENDING", "PREPARING")}
    volume = 0
    times = []
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        if row["status"] == "VERIFIED":
            volume += lamports(json.loads(row["request"])["params"]["amount"])
        if row.get("completed_at") is not None:
            times.append(max(0, row["completed_at"] - row["created_at"]))
    settled = counts["VERIFIED"] + counts["FAILED"]
    # Conservative Wilson lower bound, deliberately no bonus for volume or policy rejections.
    p = counts["VERIFIED"] / settled if settled else 0
    z = 1.96
    lower = (
        (p + z * z / (2 * settled) - z * math.sqrt(p * (1 - p) / settled + z * z / (4 * settled * settled)))
        / (1 + z * z / settled)
        if settled
        else 0
    )
    return {
        "counts": counts,
        "total": len(rows),
        "verified_lamports": volume,
        "settled": settled,
        "success_rate": round(100 * p, 1) if settled else None,
        "reliability_score": round(100 * lower, 1) if settled >= 5 else None,
        "sample_label": "Established sample"
        if settled >= 20
        else "Early sample"
        if settled >= 5
        else "Insufficient history",
        "median_resolution_seconds": sorted(times)[len(times) // 2] if times else None,
        "last_action_at": max((r["created_at"] for r in rows), default=None),
    }


def record_event(conn, user_id, kind, target):
    conn.execute(
        "INSERT INTO account_events(user_id,kind,target,created_at) VALUES(?,?,?,?)",
        (user_id, kind, target, int(time.time())),
    )


class PlatformService:
    def __init__(self, db, agents, receipts, verifier, settings):
        self.db, self.agents, self.receipts, self.verifier, self.settings = (
            db,
            agents,
            receipts,
            verifier,
            settings,
        )

    def rows(self, agent_id):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM actions WHERE agent_id=?", (agent_id,))]

    def public_agent(self, agent_id):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id=? AND listed=1", (agent_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Public agent not found")
        # Explicit projection: never publish owner identity, current whitelist or unpublished policies.
        result = {
            k: row[k]
            for k in (
                "agent_id",
                "name",
                "description",
                "public_key",
                "created_at",
                "category",
                "tagline",
                "published_at",
            )
        }
        result["active"] = bool(row["active"])
        result["metrics"] = metrics(self.rows(agent_id))
        result["network"] = "solana-devnet"
        with self.db.connect() as conn:
            offer = conn.execute("SELECT kind,version FROM agent_offers WHERE agent_id=? AND enabled=1",
                                 (agent_id,)).fetchone()
        result["offer"] = {"kind": offer["kind"], "version": offer["version"], "runtime": "tracy-managed-v1"} if offer and row["active"] else None
        return result

    def catalog(self, q="", category="", sort="recent", limit=12, offset=0):
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT agent_id FROM agents WHERE listed=1
                AND (?='' OR category=?) AND (?='' OR instr(lower(name||' '||description||' '||tagline),lower(?))>0)""",
                (category, category, q, q),
            ).fetchall()
        items = [self.public_agent(r["agent_id"]) for r in rows]
        keys = {
            "recent": lambda a: (a["published_at"] or 0, a["agent_id"]),
            "verified": lambda a: (a["metrics"]["counts"]["VERIFIED"], a["agent_id"]),
            "reliability": lambda a: (
                a["metrics"]["reliability_score"] if a["metrics"]["reliability_score"] is not None else -1,
                a["metrics"]["settled"],
                a["agent_id"],
            ),
        }
        items.sort(key=keys[sort], reverse=True)
        return {
            "items": items[offset : offset + limit],
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }

    def publish(self, agent_id, owner_id, payload):
        self.agents.get(agent_id, owner_id)
        if payload.listed and not payload.disclose_history:
            raise HTTPException(422, "Confirm publication of the complete past and future receipt history")
        with self.db.connect(write=True) as conn:
            conn.execute(
                """UPDATE agents SET listed=?,category=?,tagline=?,published_at=CASE
                WHEN ?=1 THEN COALESCE(published_at,?) ELSE NULL END WHERE agent_id=? AND owner_id=?""",
                (
                    int(payload.listed),
                    payload.category,
                    payload.tagline.strip(),
                    int(payload.listed),
                    int(time.time()),
                    agent_id,
                    owner_id,
                ),
            )
            record_event(
                conn, owner_id, "agent_published" if payload.listed else "agent_unpublished", agent_id
            )
        return self.agents.get(agent_id, owner_id)

    def public_history(self, agent_id, status="", limit=25, offset=0):
        self.public_agent(agent_id)
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT body FROM receipts WHERE agent_id=? AND (?='' OR json_extract(body,'$.status')=?)
                                   ORDER BY sequence DESC LIMIT ? OFFSET ?""",
                (agent_id, status, status, limit, offset),
            ).fetchall()
            total = conn.execute(
                """SELECT count(*) FROM receipts WHERE agent_id=? AND (?='' OR json_extract(body,'$.status')=?)""",
                (agent_id, status, status),
            ).fetchone()[0]
        return {"items": [json.loads(r["body"]) for r in rows], "total": total}

    def public_receipt(self, receipt_id):
        receipt = self.receipts.get(receipt_id)
        self.public_agent(receipt["agent_id"])
        return receipt

    def share(self, owner_id, payload):
        receipt = self.receipts.get(payload.receipt_id)
        self.agents.get(receipt["agent_id"], owner_id)
        if not payload.disclose_receipt:
            raise HTTPException(422, "Confirm that the full receipt will be visible to anyone with the link")
        share_id, now = secrets.token_urlsafe(24), int(time.time())
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO proof_shares VALUES(?,?,?,?,?,NULL)",
                (share_id, owner_id, payload.receipt_id, now, now + payload.expires_days * 86400),
            )
            record_event(conn, owner_id, "proof_shared", payload.receipt_id)
        return {
            "share_id": share_id,
            "path": "/proof/" + share_id,
            "expires_at": now + payload.expires_days * 86400,
        }

    def shares(self, owner_id):
        with self.db.connect() as conn:
            return {
                "items": [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM proof_shares WHERE user_id=? ORDER BY created_at DESC", (owner_id,)
                    )
                ]
            }

    def revoke_share(self, owner_id, share_id):
        with self.db.connect(write=True) as conn:
            if not conn.execute(
                "UPDATE proof_shares SET revoked_at=? WHERE share_id=? AND user_id=?",
                (int(time.time()), share_id, owner_id),
            ).rowcount:
                raise HTTPException(404, "Share not found")
            record_event(conn, owner_id, "proof_share_revoked", share_id)

    def shared_receipt(self, share_id):
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT receipt_id FROM proof_shares WHERE share_id=? AND revoked_at IS NULL AND expires_at>?",
                (share_id, int(time.time())),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Proof link expired, revoked or not found")
        return self.receipts.get(row["receipt_id"])

    def favorites(self, user_id):
        with self.db.connect() as conn:
            ids = [
                r[0]
                for r in conn.execute(
                    """SELECT f.agent_id FROM favorites f JOIN agents a ON a.agent_id=f.agent_id
                                               WHERE f.user_id=? AND a.listed=1 ORDER BY f.created_at DESC""",
                    (user_id,),
                )
            ]
        return {"items": [self.public_agent(i) for i in ids]}

    def favorite(self, user_id, agent_id, save):
        if save:
            self.public_agent(agent_id)
        with self.db.connect(write=True) as conn:
            if save:
                conn.execute(
                    "INSERT OR IGNORE INTO favorites VALUES(?,?,?)", (user_id, agent_id, int(time.time()))
                )
            else:
                conn.execute("DELETE FROM favorites WHERE user_id=? AND agent_id=?", (user_id, agent_id))

    def history(self, owner_id, agent_id="", status="", q="", since=0, until=0, limit=25, offset=0):
        if agent_id:
            self.agents.get(agent_id, owner_id)
        sql = """ FROM actions a JOIN agents g ON g.agent_id=a.agent_id WHERE g.owner_id=?
                  AND (?='' OR a.agent_id=?) AND (?='' OR a.status=?)
                  AND a.created_at>=? AND (?=0 OR a.created_at<=?)
                  AND (?='' OR instr(lower(a.request_id||' '||COALESCE(a.tx_signature,'')||' '||a.request||' '||g.name),lower(?))>0)"""
        args = (owner_id, agent_id, agent_id, status, status, since, until, until, q, q)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT a.*,g.name AS agent_name"
                + sql
                + " ORDER BY a.created_at DESC,a.rowid DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
            total = conn.execute("SELECT count(*)" + sql, args).fetchone()[0]
        return {"items": [unpack_action(r) for r in rows], "total": total, "limit": limit, "offset": offset}

    def export_csv(self, owner_id, **filters):
        # One consistent read, explicit bound rather than silently truncating an export.
        result = self.history(owner_id, limit=10001, **filters)
        if result["total"] > 10000:
            raise HTTPException(422, "Narrow the date or agent filters to at most 10,000 rows")
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(
            [
                "action_id",
                "agent_id",
                "agent_name",
                "status",
                "reason",
                "amount_sol",
                "recipient",
                "created_at_utc",
                "receipt_id",
                "transaction",
            ]
        )
        for row in result["items"]:
            values = [
                row["action_id"],
                row["agent_id"],
                row["agent_name"],
                row["status"],
                row["reason"],
                row["request"]["params"]["amount"],
                row["request"]["params"]["to"],
                datetime.fromtimestamp(row["created_at"], timezone.utc).isoformat(),
                row["receipt_id"],
                row["tx_signature"],
            ]
            writer.writerow(
                [
                    "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                    for v in values
                ]
            )
        return output.getvalue()

    def analytics(self, owner_id, days=30):
        now = datetime.now(timezone.utc)
        first = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db.connect() as conn:
            rows = [
                dict(r)
                for r in conn.execute(
                    """SELECT a.* FROM actions a JOIN agents g ON g.agent_id=a.agent_id
                WHERE g.owner_id=? AND a.created_at>=?""",
                    (owner_id, int(first.timestamp())),
                )
            ]
            agent_count = conn.execute(
                "SELECT count(*) FROM agents WHERE owner_id=?", (owner_id,)
            ).fetchone()[0]
        daily = []
        for d in range(days):
            day = (first + timedelta(days=d)).date().isoformat()
            selected = [
                r
                for r in rows
                if datetime.fromtimestamp(r["created_at"], timezone.utc).date().isoformat() == day
            ]
            daily.append({"day": day, **metrics(selected)})
        return {
            **metrics(rows),
            "daily": daily,
            "days": days,
            "agent_count": agent_count,
            "generated_at": int(time.time()),
        }

    def notifications(self, user_id):
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT r.receipt_id,a.agent_id,g.name AS agent_name,a.status,a.reason,a.completed_at,
                CASE WHEN n.receipt_id IS NULL THEN 0 ELSE 1 END AS is_read
                FROM receipts r JOIN actions a ON a.action_id=r.action_id JOIN agents g ON g.agent_id=a.agent_id
                LEFT JOIN notification_reads n ON n.receipt_id=r.receipt_id AND n.user_id=?
                WHERE g.owner_id=? ORDER BY r.rowid DESC LIMIT 50""",
                (user_id, user_id),
            ).fetchall()
            unread = conn.execute(
                """SELECT count(*) FROM receipts r JOIN agents a ON a.agent_id=r.agent_id
                WHERE a.owner_id=? AND NOT EXISTS(SELECT 1 FROM notification_reads n
                WHERE n.user_id=? AND n.receipt_id=r.receipt_id)""",
                (user_id, user_id),
            ).fetchone()[0]
        return {"items": [dict(r) for r in rows], "unread": unread}

    def read_notifications(self, user_id):
        with self.db.connect(write=True) as conn:
            conn.execute(
                """INSERT OR IGNORE INTO notification_reads SELECT ?,r.receipt_id FROM receipts r
                JOIN agents a ON a.agent_id=r.agent_id WHERE a.owner_id=?""",
                (user_id, user_id),
            )

    def funding(self, user_id):
        with self.db.connect() as conn:
            used = conn.execute(
                """SELECT COALESCE(sum(a.reserved_lamports),0) FROM actions a
                JOIN agents g ON g.agent_id=a.agent_id WHERE g.owner_id=? AND
                (a.budget_day=? OR a.status IN ('PENDING','PREPARING'))""",
                (user_id, utc_day()),
            ).fetchone()[0]
        cap = self.settings.owner_daily_lamports
        return {
            "day": utc_day(),
            "used_lamports": used,
            "limit_lamports": cap,
            "remaining_lamports": max(0, cap - used),
            "model": "shared_devnet_sponsor",
        }
