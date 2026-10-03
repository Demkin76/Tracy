from datetime import datetime, timezone
from decimal import Decimal

from pydantic import Field, field_validator
from solders.pubkey import Pubkey

from backend.actions.models import SolAmount, StrictModel


def lamports(amount):
    return int(Decimal(str(amount)) * 1_000_000_000)


def utc_day():
    return datetime.now(timezone.utc).date().isoformat()


class Policy(StrictModel):
    allowed_actions: list[str] = Field(default_factory=lambda: ["solana.transfer"], max_length=1)
    max_transfer_sol: SolAmount = 0.1
    daily_budget_sol: SolAmount = 1.0
    allowed_recipients: list[str] = Field(min_length=1, max_length=100)

    @field_validator("allowed_actions")
    @classmethod
    def only_transfer(cls, value):
        if any(action != "solana.transfer" for action in value):
            raise ValueError("Only solana.transfer is supported")
        return value

    @field_validator("allowed_recipients")
    @classmethod
    def valid_addresses(cls, value):
        for address in value:
            Pubkey.from_string(address)
        return list(dict.fromkeys(value))


def used_budget(conn, agent_id, day):
    # An unresolved old-day transfer can still settle today, so it continues to reserve capacity.
    return conn.execute(
        """SELECT COALESCE(sum(reserved_lamports),0) FROM actions
           WHERE agent_id=? AND (budget_day=? OR status IN ('PENDING','PREPARING'))""",
        (agent_id, day),
    ).fetchone()[0]


def evaluate(action, params, policy, sender, context=None):
    context = context or {}
    if context.get("agent_active") is False:
        return False, "agent_stopped"
    if context.get("dispatch_policy_version", context.get("policy_version")) != context.get("policy_version"):
        return False, "policy_changed_before_submission"
    if context.get("dispatch_status_version", context.get("status_version")) != context.get("status_version"):
        return False, "agent_state_changed_before_submission"
    if context.get("execution_enabled") is False:
        return False, "platform_execution_paused"
    if action not in policy["allowed_actions"]:
        return False, "action_not_allowed"
    if Decimal(str(params["amount"])) > Decimal(str(policy["max_transfer_sol"])):
        return False, "amount_exceeds_limit"
    if params["to"] not in policy["allowed_recipients"]:
        return False, "recipient_not_allowed"
    if params["to"] == sender:
        return False, "self_transfer_not_allowed"
    if "daily_used_lamports" in context and "daily_budget_sol" in policy:
        if context["daily_used_lamports"] + lamports(params["amount"]) > lamports(policy["daily_budget_sol"]):
            return False, "daily_budget_exceeded"
    for scope in ("owner", "platform"):
        if (
            scope + "_used_lamports" in context
            and context[scope + "_used_lamports"] + lamports(params["amount"])
            > context[scope + "_limit_lamports"]
        ):
            return False, scope + "_daily_budget_exceeded"
    return True, "allowed"
