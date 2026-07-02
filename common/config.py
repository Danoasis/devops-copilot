"""Central, env-driven configuration shared by every layer of the project.

Every knob has a local-first default so `git clone && uv sync && run` works with
nothing but Ollama on the host. Twelve-factor style: config lives in the
environment, not in code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # --- model backend (Ollama) ---
    ollama_base_url: str = _env("OLLAMA_BASE_URL", "http://localhost:11434")
    chat_model: str = _env("CHAT_MODEL", "qwen2.5:7b")
    embed_model: str = _env("EMBED_MODEL", "nomic-embed-text")
    judge_model: str = _env("JUDGE_MODEL", _env("CHAT_MODEL", "qwen2.5:7b"))

    # --- storage & corpus ---
    db_path: Path = Path(_env("COPILOT_DB", str(ROOT / "data" / "copilot.db")))
    kb_dir: Path = Path(_env("COPILOT_KB_DIR", str(ROOT / "day1_mcp" / "kb")))

    # --- agent guardrails ---
    max_agent_iterations: int = int(_env("MAX_AGENT_ITERATIONS", "6"))
    llm_timeout_s: float = float(_env("LLM_TIMEOUT_S", "120"))
    tool_result_max_chars: int = int(_env("TOOL_RESULT_MAX_CHARS", "4000"))

    # --- day 5 ops tools (off by default: read the guardrail story in FUNDAMENTALS ch.4) ---
    enable_ops_tools: bool = _env("COPILOT_ENABLE_OPS_TOOLS", "0") == "1"
    allow_writes: bool = _env("COPILOT_ALLOW_WRITES", "0") == "1"
    kube_namespace: str = _env("COPILOT_K8S_NAMESPACE", "default")


settings = Settings()


def openai_base_url() -> str:
    """Ollama's OpenAI-compatible endpoint (chat / tool calling)."""
    return settings.ollama_base_url.rstrip("/") + "/v1"
