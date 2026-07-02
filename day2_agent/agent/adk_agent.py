"""The same agent expressed in Google ADK (optional: `uv sync --extra adk`).

Why keep both: loop.py proves you can whiteboard the mechanism; this file proves
framework fluency (the AI JD lists ADK explicitly). LiteLLM routes ADK's model
calls to local Ollama via its OpenAI-compatible endpoint.

Run interactively:   uv run adk run day2_agent/agent      (or `adk web`)
NOTE: ADK's MCP toolset API has moved between releases; this targets google-adk>=1.0.
"""
from __future__ import annotations

import sys

from common.config import ROOT, settings

try:
    from google.adk.agents import LlmAgent
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.tools.mcp_tool.mcp_toolset import (
        MCPToolset,
        StdioServerParameters,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "google-adk is not installed. Run: uv sync --extra adk\n"
        f"(import error: {exc})"
    )

from day2_agent.agent.loop import TRIAGE_SYSTEM_PROMPT


def build_agent() -> "LlmAgent":
    return LlmAgent(
        name="devops_triage_agent",
        model=LiteLlm(
            model=f"ollama_chat/{settings.chat_model}",
            api_base=settings.ollama_base_url,
        ),
        instruction=TRIAGE_SYSTEM_PROMPT,
        tools=[
            MCPToolset(
                connection_params=StdioServerParameters(
                    command=sys.executable,
                    args=[str(ROOT / "day1_mcp" / "server.py")],
                )
            )
        ],
    )


root_agent = build_agent()
