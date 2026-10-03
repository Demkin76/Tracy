"""Optional adapter for LangChain/LangGraph; install langchain-core in the agent environment."""

from pydantic import BaseModel, Field


class ToolInput(BaseModel):
    params: dict = Field(description="Parameters of the requested operation")
    request_id: str = Field(description="Stable ID of this logical operation; reuse for retries")
    reason: str = Field(default="", description="Why this action is needed for the granted task")


def tools(protected_agent, specifications):
    from langchain_core.tools import StructuredTool

    return [
        StructuredTool.from_function(
            func=protected_agent.tool(spec["action"], spec["resource_id"]),
            name=spec["name"],
            description=spec["description"],
            args_schema=ToolInput,
            infer_schema=False,
        )
        for spec in specifications
    ]
