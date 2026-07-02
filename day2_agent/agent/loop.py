"""The hand-rolled agent loop — the whiteboard version (FUNDAMENTALS ch.4).

An agent is a bounded while-loop around an LLM:
    each iteration the model either ACTS (tool calls, which we execute against
    the MCP session) or ANSWERS (JSON we validate against a Pydantic model).

Guardrails baked in: iteration cap, per-call timeout, tool-output truncation
(done in MCPToolbox), one validation-repair retry, and an optional quality
check that can push the agent back for another round (the low-confidence
re-query that makes this an agent rather than a single RAG call).
Every LLM call and tool call is an OpenTelemetry span."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

from openai import AsyncOpenAI
from opentelemetry import trace
from pydantic import BaseModel, ValidationError

from common.config import openai_base_url, settings
from day2_agent.agent.mcp_client import MCPToolbox
from day2_agent.agent.schemas import TriageResult, schema_prompt

tracer = trace.get_tracer("devops-copilot.agent")

EventCallback = Callable[[dict[str, Any]], None]


def _extract_json(text: str) -> dict[str, Any]:
    """Tolerate models that wrap JSON in prose or ```json fences."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    return json.loads(text[start : end + 1])


class AgentError(RuntimeError):
    pass


async def run_agent(
    *,
    system_prompt: str,
    user_prompt: str,
    toolbox: MCPToolbox,
    result_model: type[BaseModel],
    on_event: EventCallback | None = None,
    quality_check: Callable[[BaseModel], str | None] | None = None,
    model: str | None = None,
    max_iterations: int | None = None,
    temperature: float = 0.2,
) -> BaseModel:
    """Run the tool-calling loop until a validated result_model is produced."""
    client = AsyncOpenAI(base_url=openai_base_url(), api_key="ollama")
    model = model or settings.chat_model
    max_iterations = max_iterations or settings.max_agent_iterations
    emit = on_event or (lambda e: None)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    repair_used = False
    nudge_used = False
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0}

    with tracer.start_as_current_span("agent.run") as run_span:
        run_span.set_attribute("gen_ai.request.model", model)

        for iteration in range(1, max_iterations + 1):
            emit({"type": "iteration", "n": iteration})
            with tracer.start_as_current_span("agent.llm_call") as span:
                span.set_attribute("iteration", iteration)
                span.set_attribute("gen_ai.request.model", model)
                try:
                    response = await asyncio.wait_for(
                        client.chat.completions.create(
                            model=model,
                            messages=messages,
                            tools=toolbox.openai_tools,
                            temperature=temperature,
                        ),
                        timeout=settings.llm_timeout_s,
                    )
                except asyncio.TimeoutError as exc:
                    raise AgentError(
                        f"LLM call timed out after {settings.llm_timeout_s}s"
                    ) from exc
                if response.usage:
                    span.set_attribute("gen_ai.usage.input_tokens",
                                       response.usage.prompt_tokens or 0)
                    span.set_attribute("gen_ai.usage.output_tokens",
                                       response.usage.completion_tokens or 0)
                    usage_totals["prompt_tokens"] += response.usage.prompt_tokens or 0
                    usage_totals["completion_tokens"] += response.usage.completion_tokens or 0
                    emit({"type": "usage", **usage_totals})

            choice = response.choices[0].message

            # --- ACT: execute every requested tool call, feed results back ---
            if choice.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": choice.content or "",
                    "tool_calls": [tc.model_dump() for tc in choice.tool_calls],
                })
                for tc in choice.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    emit({"type": "tool_call", "name": tc.function.name, "args": args})
                    with tracer.start_as_current_span("agent.tool_call") as tspan:
                        tspan.set_attribute("tool.name", tc.function.name)
                        try:
                            result = await asyncio.wait_for(
                                toolbox.call(tc.function.name, args), timeout=60
                            )
                        except Exception as exc:  # tool failure is data, not death
                            result = json.dumps({"error": f"tool failed: {exc}"})
                            tspan.record_exception(exc)
                    emit({"type": "tool_result", "name": tc.function.name,
                          "chars": len(result)})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })
                continue

            # --- ANSWER: parse + validate; one repair retry on failure ---
            raw = choice.content or ""
            try:
                result = result_model.model_validate(_extract_json(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                if repair_used:
                    raise AgentError(f"invalid final answer after repair retry: {exc}")
                repair_used = True
                emit({"type": "repair", "error": str(exc)[:300]})
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your last message was not valid JSON for the required schema. "
                        f"Error: {exc}\nRespond again with ONLY a valid JSON object, "
                        "no prose, no code fences."
                    ),
                })
                continue

            # --- quality gate: optionally push back once (real agency) ---
            if quality_check and not nudge_used:
                nudge = quality_check(result)
                if nudge:
                    nudge_used = True
                    emit({"type": "nudge", "reason": nudge})
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": nudge})
                    continue

            emit({"type": "final", "usage": usage_totals})
            run_span.set_attribute("agent.iterations", iteration)
            return result

    raise AgentError(f"no valid answer within {max_iterations} iterations")


TRIAGE_SYSTEM_PROMPT = f"""You are a senior DevOps support engineer triaging incoming tickets.

You have tools backed by a knowledge base of runbooks. Your job:
1. Read the ticket. Identify the symptom in operational terms.
2. Call search_kb with a short symptom-focused query. Refine and search again if the
   first hits look irrelevant.
3. When a hit looks right, call get_article for the full runbook before answering.
4. Answer ONLY from the runbooks you retrieved. Cite their ids. If no runbook covers
   the problem, say so plainly and use category "needs_escalation" with empty citations —
   never invent procedures.

When (and only when) you are done, respond with ONLY a JSON object matching this schema
(no prose, no code fences):

{schema_prompt(TriageResult)}
"""


def triage_quality_check(result: BaseModel) -> str | None:
    """The low-confidence re-query rule: bounded, explicit, explainable."""
    assert isinstance(result, TriageResult)
    if result.category != "needs_escalation" and not result.citations:
        return ("Your answer has no citations. Search the knowledge base again with "
                "different, more specific terms and ground your reply in a runbook, or "
                "use category needs_escalation if truly nothing applies.")
    if result.confidence < 0.4 and result.category != "needs_escalation":
        return ("Your confidence is very low. Try one more refined search_kb query to "
                "confirm or correct your answer, then respond again.")
    return None


async def run_triage(
    ticket_text: str,
    on_event: EventCallback | None = None,
    toolbox: MCPToolbox | None = None,
) -> TriageResult:
    """Triage one ticket end-to-end. Opens its own MCP session if not given one."""
    async def _run(tb: MCPToolbox) -> TriageResult:
        result = await run_agent(
            system_prompt=TRIAGE_SYSTEM_PROMPT,
            user_prompt=f"Triage this ticket:\n\n{ticket_text}",
            toolbox=tb,
            result_model=TriageResult,
            on_event=on_event,
            quality_check=triage_quality_check,
        )
        assert isinstance(result, TriageResult)
        return result

    if toolbox is not None:
        return await _run(toolbox)
    async with MCPToolbox(enable_ops_tools=False) as tb:
        return await _run(tb)
