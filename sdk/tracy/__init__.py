"""Tracy control-layer SDK. Only an intent-signing key belongs in the agent process."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import httpx

from backend.crypto.hashing import canonical_bytes
from backend.crypto.signatures import private_key, sign


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    private_seed: str

    @classmethod
    def from_file(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data["agent_id"], data["private_seed"])


class Tracy:
    def __init__(self, base_url="http://127.0.0.1:8000", task_id=None, transport=None):
        self.http = httpx.Client(base_url=base_url, timeout=30, transport=transport)
        self.task_id = task_id

    def close(self):
        self.http.close()

    def protect(self, agent, task_id=None):
        if not isinstance(agent, AgentIdentity):
            raise TypeError(
                "protect expects AgentIdentity; use the explicit framework tool adapter for LLM agents"
            )
        task = task_id or self.task_id
        if not task:
            raise ValueError("An owner-granted task_id is required")
        return ProtectedAgent(self, agent, task)

    def _post(self, path, body):
        result = self.http.post(path, json=body)
        result.raise_for_status()
        return result.json()


class ProtectedAgent:
    def __init__(self, tracy, identity, task_id):
        self.tracy, self.identity, self.task_id = tracy, identity, task_id

    def _signed(self, body):
        return {**body, "signature": sign(private_key(self.identity.private_seed), canonical_bytes(body))}

    def intent(self, action, resource_id, params, *, request_id=None, reason=""):
        body = {
            "schema_version": "tracy.intent/2",
            "request_id": request_id or "req_" + uuid4().hex,
            "agent_id": self.identity.agent_id,
            "task_id": self.task_id,
            "action": action,
            "resource_id": resource_id,
            "params": params,
            "reason": reason,
            "timestamp": int(time.time()),
        }
        return self.tracy._post("/v2/intents", self._signed(body))

    def quote(self, strategy_id):
        """Read the current paper market context using only the agent's signing key."""
        return self.tracy._post(
            "/v1/trading/quote",
            self._signed(
                {
                    "domain": "tracy.quote/3",
                    "agent_id": self.identity.agent_id,
                    "strategy_id": strategy_id,
                    "task_id": self.task_id,
                    "timestamp": int(time.time()),
                }
            ),
        )

    def status(self, intent_id):
        return self.tracy._post(
            "/v2/intents/lookup",
            self._signed(
                {
                    "domain": "tracy.lookup/2",
                    "agent_id": self.identity.agent_id,
                    "intent_id": intent_id,
                    "timestamp": int(time.time()),
                }
            ),
        )

    def wait(self, intent_id, timeout=60, interval=2):
        deadline = time.monotonic() + timeout
        while True:
            result = self.status(intent_id)
            if result["status"] in ("VERIFIED", "REJECTED", "FAILED", "AWAITING_APPROVAL", "UNCERTAIN"):
                return result
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Intent is still queued; look up its ID instead of submitting another action"
                )
            time.sleep(interval)

    def tool(self, action, resource_id):
        def guarded(params: dict, request_id: str, reason: str = ""):
            """Submit a sensitive action through Tracy. Never executes an original unprotected tool."""
            return self.intent(action, resource_id, params, request_id=request_id, reason=reason)

        return guarded
