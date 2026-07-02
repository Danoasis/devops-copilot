"""copilot-diagnose — the flagship demo: an agent that DOES DevOps.

Reuses the exact same loop as ticket triage (one architecture, two demos), but
with the ops tools enabled and an incident-response system prompt. The agent
inspects the live (kind) cluster, correlates evidence with the runbook KB, and
produces a structured IncidentReport with the exact fix — proposed, not
executed."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from day2_agent.agent.loop import run_agent
from day2_agent.agent.mcp_client import MCPToolbox
from day2_agent.agent.schemas import IncidentReport, schema_prompt

DIAGNOSE_SYSTEM_PROMPT = f"""You are a senior SRE diagnosing a live Kubernetes incident.

Method — follow it strictly:
1. get_deployments / get_pods: find the unhealthy workload (READY 0/x, CrashLoopBackOff,
   ImagePullBackOff, high restarts).
2. describe_pod on a broken pod: read Last State, exit codes, and Events.
3. If it crashed, get_pod_logs with previous=True. Collect VERBATIM evidence lines.
4. search_kb with the symptom (e.g. 'ImagePullBackOff unauthorized', 'OOMKilled 137') and
   get_article for the matching runbook. Ground your fix in it and cite it.
5. Do NOT execute any write action. Propose the exact remediation command in the report;
   the human operator decides.

When done, respond with ONLY a JSON object matching this schema (no prose, no fences):

{schema_prompt(IncidentReport)}
"""


def _print_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "tool_call":
        print(f"  -> {event['name']}({json.dumps(event['args'])})", file=sys.stderr)
    elif kind == "iteration":
        print(f"--- iteration {event['n']} ---", file=sys.stderr)


async def diagnose(prompt: str) -> IncidentReport:
    async with MCPToolbox(enable_ops_tools=True) as toolbox:
        result = await run_agent(
            system_prompt=DIAGNOSE_SYSTEM_PROMPT,
            user_prompt=prompt,
            toolbox=toolbox,
            result_model=IncidentReport,
            on_event=_print_event,
            max_iterations=10,  # inspection needs more moves than triage
        )
        assert isinstance(result, IncidentReport)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose a live cluster incident.")
    parser.add_argument(
        "prompt", nargs="?",
        default="Something is wrong in the default namespace. Find the unhealthy "
                "deployment, determine the root cause, and propose a fix.",
    )
    args = parser.parse_args()
    report = asyncio.run(diagnose(args.prompt))
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
