"""MCP 2025-11-25 stdio server. No provider tokens or approval tools in the agent process."""

import json
import os
import sys

from sdk.tracy import AgentIdentity, Tracy

VERSION = "2025-11-25"
TOOLS = [
    {
        "name": "tracy_market_context",
        "description": "Read the current synthetic paper quote for an owner-granted strategy deployment.",
        "inputSchema": {
            "type": "object",
            "properties": {"strategy_id": {"type": "string"}},
            "required": ["strategy_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tracy_intent",
        "description": "Request a sensitive action under the owner's granted task. May require human approval; never bypass Tracy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "resource_id": {"type": "string"},
                "params": {"type": "object"},
                "request_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["action", "resource_id", "params", "request_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "tracy_status",
        "description": "Read an intent's outcome and signed receipt. Does not retry execution.",
        "inputSchema": {
            "type": "object",
            "properties": {"intent_id": {"type": "string"}},
            "required": ["intent_id"],
            "additionalProperties": False,
        },
    },
]


class MCPServer:
    def __init__(self, agent):
        self.agent = agent
        self.initialized = False

    def handle(self, message):
        request_id = message.get("id")

        def error(code, text):
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": text}}

        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return error(-32600, "Invalid request")
        method = message["method"]
        if "params" in message and not isinstance(message["params"], dict):
            return error(-32602, "Parameters must be an object") if "id" in message else None
        if "id" not in message:
            if method == "notifications/initialized":
                self.initialized = True
            return None
        if method == "initialize":
            result = {
                "protocolVersion": VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tracy-control", "version": "3.0.0"},
            }
        elif method == "ping":
            result = {}
        elif not self.initialized:
            return error(-32000, "Initialize the MCP session first")
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = message.get("params", {})
            name, args = p.get("name"), p.get("arguments", {})
            if not isinstance(args, dict):
                return error(-32602, "Arguments must be an object")
            try:
                if name == "tracy_intent":
                    if not {
                        "action",
                        "resource_id",
                        "params",
                        "request_id",
                    } <= args.keys() or not args.keys() <= {
                        "action",
                        "resource_id",
                        "params",
                        "request_id",
                        "reason",
                    }:
                        return error(-32602, "Invalid intent arguments")
                    value = self.agent.intent(**args)
                elif name == "tracy_market_context" and set(args) == {"strategy_id"}:
                    value = self.agent.quote(args["strategy_id"])
                elif name == "tracy_status" and set(args) == {"intent_id"}:
                    value = self.agent.status(args["intent_id"])
                else:
                    return error(-32602, "Unknown tool or invalid arguments")
                result = {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False}
            except Exception as exc:
                # No traceback, headers, environment or connector secrets are returned to the model.
                result = {
                    "content": [{"type": "text", "text": "Tracy request failed: " + type(exc).__name__}],
                    "isError": True,
                }
        else:
            return error(-32601, "Method not found")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    identity = AgentIdentity.from_file(os.environ["TRACY_AGENT_KEY_FILE"])
    client = Tracy(
        os.environ.get("TRACY_BASE_URL", "http://127.0.0.1:8000"), task_id=os.environ["TRACY_TASK_ID"]
    )
    server = MCPServer(client.protect(identity))
    try:
        while line := sys.stdin.buffer.readline(262145):
            if len(line) > 262144:
                raise ValueError("MCP frame exceeds 256 KiB")
            try:
                request = json.loads(line)
                response = (
                    server.handle(request)
                    if isinstance(request, dict)
                    else {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid request"},
                    }
                )
            except (ValueError, TypeError):
                response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
            if response is not None:
                print(json.dumps(response), flush=True)
    finally:
        client.close()


if __name__ == "__main__":
    main()
