import os
from decimal import Decimal
from urllib.parse import quote

import httpx

from sdk.poa.signing import sign_request


class PoAClient:
    """Owner API key manages agents; the agent's Ed25519 key authorizes transfers."""

    def __init__(self, base_url="http://127.0.0.1:8000", api_key=None):
        token = api_key or os.environ.get("TRACY_API_KEY")
        self.http = httpx.Client(
            base_url=base_url,
            timeout=180,
            headers={"Authorization": f"Bearer {token}"} if token else {},
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def _call(self, method, path, **kwargs):
        response = self.http.request(method, "/v1" + path, **kwargs)
        response.raise_for_status()
        return response.json()

    def register(self, agent_id, name, public_key, policy, description=""):
        return self._call(
            "POST",
            "/agents",
            json=dict(
                agent_id=agent_id,
                name=name,
                description=description,
                public_key=public_key,
                policy=policy,
            ),
        )

    def agent(self, agent_id):
        return self._call("GET", f"/agents/{quote(agent_id, safe='')}")

    def request(self, agent_id, request_id):
        response = self.http.get(
            f"/v1/agents/{quote(agent_id, safe='')}/requests/{quote(request_id, safe='')}"
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def transfer(self, seed, agent_id, recipient, amount, request_id=None):
        return self.submit(sign_request(seed, agent_id, recipient, amount, request_id=request_id))

    def payout(self, seed, agent_id, recipient, amount, request_id):
        """Resume a stable job ID, including after the request timestamp expires."""
        if not request_id:
            raise ValueError("A stable request_id is required")
        existing = self.request(agent_id, request_id)
        if existing:
            params = existing["request"]["params"]
            if params["to"] != recipient or Decimal(str(params["amount"])) != Decimal(str(amount)):
                raise ValueError("request_id already belongs to a different payout")
            if existing["status"] == "PENDING":
                return self.reconcile(existing["action_id"])
            return existing
        try:
            return self.transfer(seed, agent_id, recipient, amount, request_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            # Another process may have submitted the same job concurrently.
            existing = self.request(agent_id, request_id)
            if existing is None:
                raise
            params = existing["request"]["params"]
            if params["to"] != recipient or Decimal(str(params["amount"])) != Decimal(str(amount)):
                raise ValueError("request_id already belongs to a different payout") from exc
            return existing

    def submit(self, signed_request):
        # Never retry a monetary operation under a fresh request_id.
        return self._call("POST", "/actions", json=signed_request)

    def reconcile(self, action_id):
        return self._call("POST", f"/actions/{quote(action_id, safe='')}/reconcile")

    def verify(self, receipt_id):
        return self._call("GET", f"/receipts/{quote(receipt_id, safe='')}/verify")

    def set_active(self, agent_id, active):
        return self._call("POST", f"/agents/{quote(agent_id, safe='')}/status", json={"active": active})

    def update_policy(self, agent_id, policy, expected_version):
        return self._call(
            "PUT",
            f"/agents/{quote(agent_id, safe='')}/policy",
            json={"policy": policy, "expected_version": expected_version},
        )

    def history(self, agent_id="", status="", limit=25, offset=0):
        return self._call(
            "GET",
            "/history",
            params={"agent_id": agent_id, "status": status, "limit": limit, "offset": offset},
        )

    def publish(self, agent_id, *, disclose_history, category="payouts", tagline=""):
        return self._call(
            "PUT",
            f"/agents/{quote(agent_id, safe='')}/publication",
            json={
                "listed": True,
                "disclose_history": disclose_history,
                "category": category,
                "tagline": tagline,
            },
        )

    def unpublish(self, agent_id):
        return self._call("PUT", f"/agents/{quote(agent_id, safe='')}/publication", json={"listed": False})

    def share(self, receipt_id, *, disclose_receipt, expires_days=7):
        return self._call(
            "POST",
            "/shares",
            json={
                "receipt_id": receipt_id,
                "disclose_receipt": disclose_receipt,
                "expires_days": expires_days,
            },
        )

    def revoke_share(self, share_id):
        return self._call("DELETE", f"/shares/{quote(share_id, safe='')}")

    def catalog(self, query="", category="", sort="recent"):
        return self._call("GET", "/public/agents", params={"q": query, "category": category, "sort": sort})

    def public_agent(self, agent_id):
        return self._call("GET", f"/public/agents/{quote(agent_id, safe='')}")

    def verify_shared(self, share_id):
        return self._call("GET", f"/public/proofs/{quote(share_id, safe='')}/verify")
