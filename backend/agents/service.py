import json
import sqlite3
import time

from fastapi import HTTPException

from backend.platform.service import record_event
from backend.policies.engine import lamports, used_budget, utc_day


class AgentService:
    def __init__(self, db):
        self.db = db

    def register(self, request, owner_id):
        try:
            with self.db.connect(write=True) as conn:
                if (
                    conn.execute("SELECT count(*) FROM agents WHERE owner_id=?", (owner_id,)).fetchone()[0]
                    >= 50
                ):
                    raise HTTPException(409, "Workspace limit: 50 agents")
                conn.execute(
                    """INSERT INTO agents(agent_id,name,public_key,created_at,policy,owner_id,description)
                                VALUES(?,?,?,?,?,?,?)""",
                    (
                        request.agent_id,
                        request.name,
                        request.public_key,
                        int(time.time()),
                        json.dumps(request.policy.model_dump()),
                        owner_id,
                        request.description,
                    ),
                )
                conn.execute(
                    "INSERT INTO policy_versions VALUES(?,?,?,?,?)",
                    (
                        request.agent_id,
                        1,
                        json.dumps(request.policy.model_dump()),
                        int(time.time()),
                        owner_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Agent ID already exists; choose another ID") from exc
        with self.db.connect(write=True) as conn:
            record_event(conn, owner_id, "agent_created", request.agent_id)
        return self.get(request.agent_id, owner_id)

    def get(self, agent_id, owner_id=None):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            if row is None or (owner_id is not None and row["owner_id"] != owner_id):
                raise HTTPException(404, "Agent not found")
            result = dict(row)
            day = utc_day()
            used = used_budget(conn, agent_id, day)
        result["policy"] = json.loads(result["policy"])
        result["active"] = bool(result["active"])
        with self.db.connect() as conn:
            result["managed"] = conn.execute("SELECT 1 FROM installations WHERE agent_id=?", (agent_id,)).fetchone() is not None
        cap = lamports(result["policy"].get("daily_budget_sol", 1.0))
        result["budget"] = {
            "day": day,
            "timezone": "UTC",
            "used_lamports": used,
            "limit_lamports": cap,
            "remaining_lamports": max(0, cap - used),
        }
        return result

    def list(self, owner_id):
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM agents WHERE owner_id=? ORDER BY created_at DESC,rowid DESC LIMIT 500",
                (owner_id,),
            ).fetchall()
        return [self.get(row["agent_id"], owner_id) for row in rows]

    def profile(self, agent_id, owner_id, payload):
        self.get(agent_id, owner_id)
        if not payload.name.strip():
            raise HTTPException(422, "Name cannot be blank")
        with self.db.connect(write=True) as conn:
            conn.execute(
                "UPDATE agents SET name=?,description=? WHERE agent_id=? AND owner_id=?",
                (payload.name.strip(), payload.description, agent_id, owner_id),
            )
            record_event(conn, owner_id, "agent_profile_updated", agent_id)
        return self.get(agent_id, owner_id)

    def status(self, agent_id, owner_id, active):
        self.get(agent_id, owner_id)
        with self.db.connect(write=True) as conn:
            conn.execute(
                "UPDATE agents SET active=?,status_version=status_version+1 WHERE agent_id=? AND owner_id=?",
                (int(active), agent_id, owner_id),
            )
            if not active:
                conn.execute("UPDATE installations SET running=0,next_run_at=NULL WHERE agent_id=?", (agent_id,))
                conn.execute("""UPDATE agent_runs SET status='CANCELLED',reason='owner_stopped',
                    completed_at=? WHERE agent_id=? AND status IN ('QUEUED','RUNNING','WAITING')""",
                    (int(time.time()), agent_id))
            record_event(conn, owner_id, "agent_resumed" if active else "agent_stopped", agent_id)
        return self.get(agent_id, owner_id)

    def update_policy(self, agent_id, owner_id, payload):
        with self.db.connect(write=True) as conn:
            agent = conn.execute(
                "SELECT * FROM agents WHERE agent_id=? AND owner_id=?", (agent_id, owner_id)
            ).fetchone()
            if not agent:
                raise HTTPException(404, "Agent not found")
            if agent["policy_version"] != payload.expected_version:
                raise HTTPException(409, "Policy changed in another session; reload before saving")
            version = agent["policy_version"] + 1
            body = json.dumps(payload.policy.model_dump())
            conn.execute(
                "INSERT INTO policy_versions VALUES(?,?,?,?,?)",
                (agent_id, version, body, int(time.time()), owner_id),
            )
            conn.execute(
                "UPDATE agents SET policy=?,policy_version=? WHERE agent_id=?", (body, version, agent_id)
            )
            record_event(conn, owner_id, "policy_updated", agent_id)
        return self.get(agent_id, owner_id)

    def versions(self, agent_id, owner_id):
        self.get(agent_id, owner_id)
        with self.db.connect() as conn:
            return [
                {**dict(row), "policy": json.loads(row["body"])}
                for row in conn.execute(
                    "SELECT version,body,created_at,created_by FROM policy_versions WHERE agent_id=? ORDER BY version DESC",
                    (agent_id,),
                )
            ]
