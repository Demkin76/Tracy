"""Local contract simulator. Never connects to GitHub and never bills money."""

import hmac
import json
import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/control-provider.sqlite3"


def authorized(authorization: str = Header("")):
    secrets = json.loads((ROOT / "data/control-credentials.json").read_text())
    expected = "Bearer " + secrets["TRACY_LOCAL_PROVIDER_TOKEN"]
    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Provider credential required")


def connection():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,body TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pulls(number INTEGER PRIMARY KEY AUTOINCREMENT,body TEXT NOT NULL)"
    )
    return conn


app = FastAPI(title="Tracy local test provider", dependencies=[Depends(authorized)])


@app.post("/execute")
async def execute(request: Request):
    value = await request.json()
    if request.headers.get("idempotency-key") != value["intent_id"]:
        raise HTTPException(400, "Idempotency key mismatch")
    body = {
        **value,
        "status": "completed",
        "result": {"summary": "Local test operation completed", "billable": False},
    }
    with connection() as conn:
        old = conn.execute("SELECT body FROM operations WHERE id=?", (value["intent_id"],)).fetchone()
        if old:
            previous = json.loads(old[0])
            if previous["request_hash"] != value["request_hash"]:
                raise HTTPException(409, "Different intent for the same key")
            return previous
        conn.execute("INSERT INTO operations VALUES(?,?)", (value["intent_id"], json.dumps(body)))
    return body


@app.get("/operations/{operation_id}")
def operation(operation_id: str):
    with connection() as conn:
        row = conn.execute("SELECT body FROM operations WHERE id=?", (operation_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown operation")
    return json.loads(row[0])


@app.get("/repos/{owner}/{repo}/commits/{branch:path}")
def commit(owner: str, repo: str, branch: str):
    return {"sha": "a" * 40, "test_only": True}


@app.post("/repos/{owner}/{repo}/pulls")
async def create_pull(owner: str, repo: str, request: Request):
    p = await request.json()
    body = {
        "title": p["title"],
        "body": p["body"],
        "draft": True,
        "test_only": True,
        "state": "open",
        "head": {"sha": "a" * 40, "ref": p["head"]},
        "base": {"ref": p["base"], "repo": {"full_name": owner + "/" + repo}},
    }
    with connection() as conn:
        cursor = conn.execute("INSERT INTO pulls(body) VALUES(?)", (json.dumps(body),))
        body["number"] = cursor.lastrowid
        body["html_url"] = (
            "http://127.0.0.1:8011/repos/" + owner + "/" + repo + "/pulls/" + str(body["number"])
        )
        conn.execute("UPDATE pulls SET body=? WHERE number=?", (json.dumps(body), body["number"]))
    return body


@app.get("/repos/{owner}/{repo}/pulls/{number}")
def pull(owner: str, repo: str, number: int):
    with connection() as conn:
        row = conn.execute("SELECT body FROM pulls WHERE number=?", (number,)).fetchone()
    if not row:
        raise HTTPException(404, "Unknown test pull request")
    return json.loads(row[0])


@app.get("/repos/{owner}/{repo}/pulls")
def pulls(owner: str, repo: str, head: str = "", base: str = ""):
    with connection() as conn:
        rows = [
            json.loads(r[0]) for r in conn.execute("SELECT body FROM pulls ORDER BY number DESC LIMIT 100")
        ]
    return [
        r
        for r in rows
        if r["base"]["repo"]["full_name"] == owner + "/" + repo
        and (not head or r["head"]["ref"] == head.split(":")[-1])
        and (not base or r["base"]["ref"] == base)
    ]
