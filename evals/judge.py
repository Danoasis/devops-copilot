"""LLM-as-judge for triage replies (FUNDAMENTALS ch.11).

Design rules baked in here:

1. The judge model should differ from the agent model when possible
   (JUDGE_MODEL env var) — never let a model grade its own homework.
2. Rubric-anchored scoring: each dimension is scored 0 / 0.5 / 1 against
   written anchors, not a vague 1-10 scale. Coarse scales are far more
   reproducible across runs and across judge models.
3. The judge sees the *evidence*, not just the answer: we hand it the full
   text of every runbook the agent cited so "groundedness" is checked
   against the actual source, not the judge's own world knowledge.
4. Deterministic-ish: temperature 0, JSON-only output, tolerant parsing
   with one repair attempt — same tricks as the agent loop.

Everything here is sync (plain httpx) because the eval runner is a CLI,
not a service; no need for asyncio.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from common.config import settings

RUBRIC = """\
You are a strict evaluator of an IT support triage assistant. Score the
assistant's reply on three dimensions. Use ONLY these anchor definitions.

groundedness — is every substantive claim supported by the provided runbooks?
  1.0  every diagnostic claim and command in the reply appears in, or follows
       directly from, the cited runbook excerpts.
  0.5  mostly supported, but at least one concrete claim/command is not in the
       runbooks (even if it happens to be plausible).
  0.0  the reply leans on invented facts, or cites runbooks that do not
       actually support it, or cites nothing while making concrete claims.

correctness — would following the reply actually resolve (or correctly
escalate) the ticket?
  1.0  the diagnosis matches the ticket's symptoms and the steps are the right
       ones, in a sensible order.
  0.5  partially right: correct general direction but a wrong/missing key step,
       or correct steps for a sibling problem.
  0.0  wrong diagnosis, harmful advice, or confidently answers something the
       runbooks cannot answer instead of escalating.

helpfulness — could a mid-level engineer act on this reply immediately?
  1.0  concrete: names the commands/settings to check, in order, with what to
       look for; appropriately concise.
  0.5  generically useful but vague ("check the logs", "verify configuration")
       or bloated with irrelevant material.
  0.0  restates the problem, dodges, or is unusable.

Respond with ONLY a JSON object, no markdown fences, no commentary:
{"groundedness": <0|0.5|1>, "correctness": <0|0.5|1>, "helpfulness": <0|0.5|1>,
 "rationale": "<one or two sentences>"}
"""


@dataclass
class JudgeScore:
    groundedness: float
    correctness: float
    helpfulness: float
    rationale: str
    error: str | None = None

    @property
    def mean(self) -> float:
        return (self.groundedness + self.correctness + self.helpfulness) / 3


def load_cited_sources(citations: list[str], kb_dir: Path | None = None) -> str:
    """Return the full text of every cited runbook (or a marker if missing).

    The judge must see what the agent saw. A citation to a nonexistent
    article is itself evidence of hallucination, so we surface that
    explicitly rather than silently skipping it.
    """
    kb_dir = kb_dir or settings.kb_dir
    parts: list[str] = []
    for cid in citations:
        matches = sorted(kb_dir.glob(f"{cid}*.md"))
        if matches:
            parts.append(f"--- {cid} ---\n{matches[0].read_text(encoding='utf-8')}")
        else:
            parts.append(f"--- {cid} ---\n[NO SUCH RUNBOOK EXISTS IN THE KB]")
    return "\n\n".join(parts) if parts else "[the assistant cited no runbooks]"


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL)
    m = _JSON_RE.search(text)
    if not m:
        raise ValueError(f"judge returned no JSON: {text[:200]!r}")
    return json.loads(m.group(0))


def _snap(value: object) -> float:
    """Snap a judge score to the nearest rubric anchor {0, 0.5, 1}."""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return min((0.0, 0.5, 1.0), key=lambda a: abs(a - v))


def judge_reply(ticket: str, result: dict, *, client: httpx.Client | None = None,
                model: str | None = None) -> JudgeScore:
    """Score one triage result. Never raises: judge failures are recorded
    as error scores so a flaky judge model can't crash the whole eval run
    (the scorecard will show judged_n < n and you can rerun)."""
    model = model or settings.judge_model
    sources = load_cited_sources(result.get("citations", []))
    user_msg = (
        f"TICKET:\n{ticket}\n\n"
        f"ASSISTANT REPLY (category={result.get('category')}, "
        f"confidence={result.get('confidence')}):\n{result.get('suggested_reply', '')}\n\n"
        f"CITED RUNBOOKS:\n{sources}"
    )
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": user_msg},
        ],
    }
    own_client = client is None
    client = client or httpx.Client(timeout=settings.llm_timeout_s)
    try:
        resp = client.post(f"{settings.openai_base_url()}/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)
        return JudgeScore(
            groundedness=_snap(data.get("groundedness")),
            correctness=_snap(data.get("correctness")),
            helpfulness=_snap(data.get("helpfulness")),
            rationale=str(data.get("rationale", ""))[:500],
        )
    except Exception as exc:  # noqa: BLE001 — deliberate: record, don't crash
        return JudgeScore(0.0, 0.0, 0.0, rationale="", error=f"{type(exc).__name__}: {exc}")
    finally:
        if own_client:
            client.close()
