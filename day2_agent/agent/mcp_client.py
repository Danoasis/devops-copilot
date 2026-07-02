"""Async MCP client wrapper: spawns the Day 1 server over stdio, discovers its
tools, converts their schemas to the OpenAI tool format, and executes calls.

Discovery is the point of MCP — nothing here hard-codes a tool name."""
from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from common.config import ROOT, settings

SERVER_PATH = ROOT / "day1_mcp" / "server.py"


class MCPToolbox:
    """Async context manager holding one live MCP session.

    Usage:
        async with MCPToolbox() as toolbox:
            result = await toolbox.call("search_kb", {"query": "..."})
    """

    def __init__(self, enable_ops_tools: bool | None = None) -> None:
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.openai_tools: list[dict[str, Any]] = []
        self._enable_ops = (
            settings.enable_ops_tools if enable_ops_tools is None else enable_ops_tools
        )

    async def __aenter__(self) -> "MCPToolbox":
        env = dict(os.environ)
        env["COPILOT_ENABLE_OPS_TOOLS"] = "1" if self._enable_ops else "0"
        # Make `import common` work in the child even from a bare checkout
        # (no uv/pip install): prepend the repo root to its PYTHONPATH.
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        params = StdioServerParameters(
            command=sys.executable, args=[str(SERVER_PATH)], env=env, cwd=str(ROOT)
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listed = await self.session.list_tools()
        self.openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema
                    or {"type": "object", "properties": {}},
                },
            }
            for t in listed.tools
        ]
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        assert self.session is not None, "toolbox used outside its context"
        result = await self.session.call_tool(name, arguments)
        parts = [c.text for c in result.content if getattr(c, "text", None)]
        text = "\n".join(parts) if parts else "(empty tool result)"
        limit = settings.tool_result_max_chars
        if len(text) > limit:
            text = text[:limit] + f"\n...[truncated at {limit} chars]"
        return text


def default_kb_path_note() -> str:
    return f"MCP server: {SERVER_PATH} (kb: {Path(settings.kb_dir).resolve()})"
