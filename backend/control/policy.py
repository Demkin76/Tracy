def evaluate(policy, request, c):
    if not c["agent_active"]:
        return "deny", "agent_stopped"
    if not c["execution_enabled"]:
        return "deny", "platform_execution_paused"
    if not c["task_active"] or c["task_expires_at"] <= c["now"]:
        return "deny", "task_expired_or_revoked"
    if (
        request["action"] not in c["task"]["allowed_actions"]
        or request["resource_id"] not in c["task"]["allowed_resources"]
    ):
        return "deny", "outside_task_scope"
    if c.get("validation_error"):
        return "deny", c["validation_error"]
    rule = next(
        (
            r
            for r in policy["rules"]
            if r["action"] == request["action"] and r["resource_id"] == request["resource_id"]
        ),
        None,
    )
    if not rule:
        return "deny", "action_or_resource_not_allowed"
    if c["target"] not in rule["allowed_targets"]:
        return "deny", "target_not_allowed"
    if c["units"] > rule["max_units_per_action"]:
        return "deny", "per_action_limit_exceeded"
    if c["used_units"] + c["units"] > rule["daily_units"]:
        return "deny", "daily_budget_exceeded"
    if c["recent_count"] >= policy["max_per_minute"]:
        return "deny", "anomaly_request_rate"
    if c["denial_count"] >= policy["max_denials_per_hour"]:
        return "deny", "anomaly_repeated_denials"
    for scope in ("owner", "platform"):
        if c.get(scope + "_used", 0) + c["units"] > c.get(scope + "_limit", 9_000_000_000_000_000):
            return "deny", scope + "_budget_exceeded"
    if c.get("dispatch_policy_version", c["policy_version"]) != c["policy_version"]:
        return "deny", "policy_changed_before_execution"
    if c.get("dispatch_status_version", c["status_version"]) != c["status_version"]:
        return "deny", "agent_state_changed_before_execution"
    if c.get("connector_changed"):
        return "deny", "connector_changed_before_execution"
    if rule["require_approval"]:
        return "review", "human_approval_required"
    if policy["review_new_targets"] and not c["target_seen"]:
        return "review", "anomaly_new_target"
    return "allow", "policy_allowed"
