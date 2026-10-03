"""Run with an agent-only key and an owner-granted task. No owner/provider credentials."""

import os
from sdk.tracy import AgentIdentity, Tracy

client = Tracy(os.environ.get("TRACY_BASE_URL", "http://127.0.0.1:8000"), task_id=os.environ["TRACY_TASK_ID"])
try:
    agent = client.protect(AgentIdentity.from_file(os.environ["TRACY_AGENT_KEY_FILE"]))
    result = agent.intent(
        "database.insert",
        os.environ.get("TRACY_RESOURCE_ID", "demo-records"),
        {"record": {"message": "A result submitted by my agent"}},
        request_id=os.environ["TRACY_REQUEST_ID"],
        reason="Store the task result",
    )
    print(result["intent_id"], result["status"])
    print(agent.wait(result["intent_id"])["status"])
finally:
    client.close()
