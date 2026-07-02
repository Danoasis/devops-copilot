"""Structured outputs: never let an agent's machine-consumed answer be free prose
(FUNDAMENTALS ch.4). Pydantic models double as the validation gate and as the
JSON schema shown to the model in the system prompt."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal[
    "kubernetes", "ci_cd", "infrastructure", "security", "observability", "needs_escalation"
]


class TriageResult(BaseModel):
    category: Category = Field(description="Best-fit incident category.")
    suggested_reply: str = Field(
        description="A grounded reply to the ticket: likely cause, concrete next steps, "
                    "and the exact commands to run. Must be supported by the cited runbooks."
    )
    citations: list[str] = Field(
        default_factory=list,
        description="Runbook ids (e.g. 'KB-003') that support the reply. Empty ONLY when "
                    "category is needs_escalation because the KB has no relevant runbook.",
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Self-assessed confidence 0..1.")


class IncidentReport(BaseModel):
    deployment: str = Field(description="Name of the affected Kubernetes deployment.")
    root_cause: str = Field(description="One-paragraph root cause, stated plainly.")
    evidence: list[str] = Field(
        description="Verbatim log lines / event messages / pod states that prove it."
    )
    cited_runbooks: list[str] = Field(description="Runbook ids consulted, e.g. ['KB-002'].")
    recommended_fix: str = Field(description="What to change and why.")
    remediation_command: str = Field(
        description="The exact command that would fix it. Propose only; do not execute "
                    "unless the operator confirms."
    )
    confidence: float = Field(ge=0.0, le=1.0)


def schema_prompt(model: type[BaseModel]) -> str:
    """Render a model's JSON schema for inclusion in a system prompt."""
    return json.dumps(model.model_json_schema(), indent=2)
