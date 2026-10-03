"""Operator-owned resource registry; credentials never enter agent requests or API responses."""

import importlib
import ipaddress
import json
import os
import re
import socket
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from fastapi import HTTPException

from backend.actions.models import TransferParams
from backend.blockchain.solana import PreparedTransfer
from backend.crypto.hashing import canonical_bytes, digest


class Registry:
    def __init__(self, settings, gateway):
        self.settings, self.gateway = settings, gateway

    def resources(self):
        items = [
            {"id": "devnet-wallet", "kind": "solana", "label": "Tracy Devnet signer", "owner_ids": ["*"]}
        ]
        path = self.settings.control_resources_path
        if path.is_file():
            items += json.loads(path.read_text(encoding="utf-8"))["resources"]
        ids = [r["id"] for r in items]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate control resource ID")
        return items

    def get(self, resource_id, owner_id):
        for item in self.resources():
            if item["id"] == resource_id and ("*" in item["owner_ids"] or owner_id in item["owner_ids"]):
                return item
        raise HTTPException(404, "Resource is not assigned to this workspace")

    def adapter(self, resource):
        classes = {
            "solana": SolanaAdapter,
            "database": DatabaseAdapter,
            "github": GitHubAdapter,
            "http": HttpAdapter,
        }
        if resource["kind"] == "plugin":
            module, name = resource["adapter"].split(":", 1)
            factory = getattr(importlib.import_module(module), name)
            if not isinstance(factory, type) or not issubclass(factory, Adapter):
                raise ValueError("Operator plugin must implement the Adapter contract")
            return factory(resource, self)
        if resource["kind"] not in classes:
            raise ValueError("Unsupported connector")
        return classes[resource["kind"]](resource, self)

    def public(self, owner_id):
        result = []
        for r in self.resources():
            if "*" in r["owner_ids"] or owner_id in r["owner_ids"]:
                a = self.adapter(r)
                result.append(
                    {
                        "id": r["id"],
                        "kind": r["kind"],
                        "label": r.get("label", r["id"]),
                        "actions": a.actions,
                        "asset": a.asset,
                        "configured": a.configured(),
                        "trust_boundary": a.boundary,
                        "unit_description": a.unit_description,
                    }
                )
        return result


class Adapter:
    boundary = "Credentials are held by the Tracy operator."
    asset = "operations"
    unit_description = "One authorized operation"
    actions = []

    def __init__(self, config, registry):
        self.config, self.registry = config, registry

    def configured(self):
        return True

    def validate(self, action, params):
        if action not in self.actions:
            raise ValueError("Action is not supported by this resource")

    async def prepare(self, request, intent_id, intent_hash):
        return {"intent_id": intent_id, "intent_hash": intent_hash, "params": request["params"]}

    async def execute(self, prepared):
        raise NotImplementedError

    async def verify(self, prepared, result):
        raise NotImplementedError


class SolanaAdapter(Adapter):
    actions = ["solana.transfer"]
    asset = "SOL-lamports"
    unit_description = "1 SOL = 1,000,000,000 lamports"
    boundary = "Only Tracy holds the Devnet execution wallet key; agent signing keys cannot spend it."

    def validate(self, action, params):
        super().validate(action, params)
        p = TransferParams.model_validate(params)
        if p.to == self.registry.gateway.sender:
            raise ValueError("Self-transfer is not permitted")
        return p.to, p.lamports

    async def prepare(self, request, intent_id, intent_hash):
        p = TransferParams.model_validate(request["params"])
        tx = await self.registry.gateway.prepare(p.to, p.lamports, intent_hash)
        # Signed bytes stay in the server DB. Public responses must never expose them before dispatch.
        return {
            "signature": tx.signature,
            "raw": tx.raw.hex(),
            "params": request["params"],
            "intent_hash": intent_hash,
            "sender": self.registry.gateway.sender,
        }

    async def execute(self, prepared):
        await self.registry.gateway.broadcast(
            PreparedTransfer(bytes.fromhex(prepared["raw"]), prepared["signature"])
        )
        return {"tx_signature": prepared["signature"]}

    async def verify(self, prepared, result):
        p = TransferParams.model_validate(prepared["params"])
        evidence = await self.registry.gateway.verify_transfer(
            prepared["signature"], prepared["sender"], p.to, p.lamports, prepared["intent_hash"]
        )
        return {
            **evidence.to_dict(),
            "source": "independent_solana_rpc",
            "external_id": prepared["signature"],
        }


class DatabaseAdapter(Adapter):
    actions = ["database.insert"]
    boundary = "Operator-owned database; only fixed parameterized inserts into tracy_records. Agent gets no SQL access."

    def path(self):
        path = Path(self.config["path"]).resolve()
        if path == self.registry.settings.database_path.resolve():
            raise ValueError("Connector database must be separate from Tracy's own database")
        return path

    def validate(self, action, params):
        super().validate(action, params)
        if set(params) != {"record"} or not isinstance(params["record"], dict):
            raise ValueError("database.insert requires exactly a record object")
        if len(canonical_bytes(params)) > 8192:
            raise ValueError("Record exceeds 8 KiB")
        self.path()
        return "tracy_records", 1

    async def execute(self, prepared):
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS tracy_records(
                intent_id TEXT PRIMARY KEY,request_hash TEXT NOT NULL,payload TEXT NOT NULL)""")
            conn.execute(
                "INSERT OR IGNORE INTO tracy_records VALUES(?,?,?)",
                (prepared["intent_id"], prepared["intent_hash"], json.dumps(prepared["params"]["record"])),
            )
        return {"record_id": prepared["intent_id"]}

    async def verify(self, prepared, result):
        path = self.path()
        if not path.is_file():
            return {"status": "pending", "source": "database_readback", "reason": "record_not_observed"}
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
            try:
                row = conn.execute(
                    "SELECT request_hash,payload FROM tracy_records WHERE intent_id=?",
                    (prepared["intent_id"],),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None
        good = (
            row and row[0] == prepared["intent_hash"] and json.loads(row[1]) == prepared["params"]["record"]
        )
        return {
            "status": "verified" if good else "mismatch" if row else "pending",
            "source": "database_readback",
            "reason": "record_matches_intent" if good else "record_not_matched",
            "external_id": prepared["intent_id"],
        }


class NetworkAdapter(Adapter):
    def token(self):
        name = self.config.get("token_env", "")
        token = os.environ.get(name, "")
        path = self.registry.settings.control_credentials_path
        if not token and path.is_file():
            token = json.loads(path.read_text(encoding="utf-8")).get(name, "")
        return token

    def configured(self):
        return bool(self.token())

    def base(self):
        url = self.config["base_url"].rstrip("/")
        parsed = urlparse(url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Resource URL cannot contain credentials, query or fragment")
        addresses = [
            ipaddress.ip_address(r[4][0]) for r in socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        ]
        local_test = self.config.get("local_test") is True and all(a.is_loopback for a in addresses)
        if not local_test and (parsed.scheme != "https" or any(not a.is_global for a in addresses)):
            raise ValueError(
                "Resource must use HTTPS and public addresses; private networks require explicit operator configuration"
            )
        if local_test and parsed.scheme not in ("http", "https"):
            raise ValueError("Invalid local test URL")
        return url

    async def call(self, method, path, **kwargs):
        if not self.token():
            raise RuntimeError("Connector credential is not configured on the server")
        # Agent input never determines host, port, headers or request path.
        headers = {"Authorization": "Bearer " + self.token(), "Accept": "application/json"}
        headers.update(kwargs.pop("headers", {}))
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, self.base() + path, headers=headers, **kwargs) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1048576:
                        raise RuntimeError("Connector response exceeds 1 MiB")
                if response.status_code == 404:
                    return None
                if not 200 <= response.status_code < 300:
                    raise RuntimeError("Connector returned HTTP " + str(response.status_code))
                return json.loads(body)


class HttpAdapter(NetworkAdapter):
    actions = ["http.invoke"]
    boundary = "Fixed operator-configured endpoint; server-side credential. Provider must support request-hash readback."
    unit_description = "Configured cost units per invocation; provider billing must be capped separately."

    @property
    def asset(self):
        return self.config.get("asset", "USD-micros")

    def validate(self, action, params):
        super().validate(action, params)
        allowed = self.config.get("allowed_fields", [])
        required = self.config.get("required_fields", [])
        if not set(params) <= set(allowed) or not set(required) <= set(params):
            raise ValueError("HTTP parameters do not match this resource's fixed contract")
        units = self.config.get("units_per_call", 1)
        if type(units) is not int or units < 1:
            raise ValueError("Invalid operator cost configuration")
        return self.config.get("operation", "invoke"), units

    async def execute(self, prepared):
        await self.call(
            "POST",
            "/execute",
            headers={"Idempotency-Key": prepared["intent_id"]},
            json={
                "intent_id": prepared["intent_id"],
                "request_hash": prepared["intent_hash"],
                "params": prepared["params"],
            },
        )

        return {"operation_id": prepared["intent_id"]}

    async def verify(self, prepared, result):
        record = await self.call("GET", "/operations/" + quote(prepared["intent_id"], safe=""))
        if record is None:
            return {"status": "pending", "reason": "operation_not_observed", "source": "provider_readback"}
        matches = (
            record.get("request_hash") == prepared["intent_hash"]
            and record.get("params") == prepared["params"]
        )
        if matches and record.get("status") in ("pending", "running"):
            return {
                "status": "pending",
                "reason": "provider_operation_pending",
                "source": "provider_readback",
            }
        good = matches and record.get("status") == "completed"
        return {
            "status": "verified" if good else "mismatch",
            "reason": "provider_record_matches" if good else "provider_record_mismatch",
            "source": "provider_readback",
            "external_id": prepared["intent_id"],
            "result_hash": digest(record),
        }


class GitHubAdapter(NetworkAdapter):
    actions = ["github.pull_request"]
    boundary = "Fine-grained token stays on the server and is limited to the configured repository. Existing branches only."

    def validate(self, action, params):
        super().validate(action, params)
        if not {"head", "base", "title", "body", "head_sha"} == set(params):
            raise ValueError("PR requires head, base, title, body and head_sha")
        if any(not isinstance(v, str) for v in params.values()):
            raise ValueError("PR fields must be strings")
        if not all(
            re.fullmatch(r"[A-Za-z0-9_./-]{1,150}", params[k]) and ".." not in params[k]
            for k in ("head", "base")
        ):
            raise ValueError("Invalid branch reference")
        if params["head"] == params["base"] or not re.fullmatch(r"[0-9a-f]{40}", params["head_sha"]):
            raise ValueError("Pin the head commit SHA and use distinct branches")
        if not 1 <= len(params["title"]) <= 200 or len(params["body"]) > 8000:
            raise ValueError("PR title/body exceeds limits")
        return self.config["repository"], 1

    def repo_path(self):
        repo = self.config["repository"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid repository configuration")
        return "/repos/" + repo

    async def prepare(self, request, intent_id, intent_hash):
        prepared = await super().prepare(request, intent_id, intent_hash)
        p = request["params"]
        branch = await self.call("GET", self.repo_path() + "/commits/" + quote(p["head"], safe=""))
        if not branch or branch.get("sha") != p["head_sha"]:
            raise ValueError("Head branch no longer matches the reviewed commit")
        prepared["body"] = p["body"] + "\n\n<!-- tracy:" + intent_id + ":" + intent_hash + " -->"
        return prepared

    async def execute(self, prepared):
        p = prepared["params"]
        response = await self.call(
            "POST",
            self.repo_path() + "/pulls",
            json={
                "head": p["head"],
                "base": p["base"],
                "title": p["title"],
                "body": prepared["body"],
                "draft": True,
            },
        )
        return {"number": response["number"]}

    async def verify(self, prepared, result):
        p = prepared["params"]
        if result and type(result.get("number")) is int:
            candidates = [await self.call("GET", self.repo_path() + "/pulls/" + str(result["number"]))]
        else:
            candidates = await self.call(
                "GET",
                self.repo_path() + "/pulls",
                params={
                    "state": "all",
                    "head": self.config["repository"].split("/")[0] + ":" + p["head"],
                    "base": p["base"],
                    "per_page": 100,
                },
            )
        rows = [r for r in candidates or [] if r and r.get("body") == prepared["body"]]
        if not rows:
            return {"status": "pending", "reason": "pull_request_not_observed", "source": "github_readback"}
        r = rows[0]
        good = (
            len(rows) == 1
            and r.get("draft") is True
            and r.get("title") == p["title"]
            and r.get("head", {}).get("sha") == p["head_sha"]
            and r.get("head", {}).get("ref") == p["head"]
            and r.get("base", {}).get("ref") == p["base"]
            and r.get("base", {}).get("repo", {}).get("full_name") == self.config["repository"]
        )
        return {
            "status": "verified" if good else "mismatch",
            "reason": "pull_request_matches_intent" if good else "pull_request_mismatch",
            "source": "github_readback",
            "external_id": r.get("number"),
            "url": r.get("html_url"),
        }
