"""Cluster ops tools for the MCP server — the 'agentic AI automating DevOps
workflows' layer, built on the guardrail philosophy (FUNDAMENTALS ch.4):

  * READ-ONLY BY DEFAULT: inspection tools only.
  * Writes are DOUBLY gated: the tool demands confirm=True from the model AND
    the operator must have set COPILOT_ALLOW_WRITES=1 in the environment.
    An agent with kubectl is a loaded weapon; the safety is mechanical, not
    a polite request in the prompt.
  * Everything shells out to kubectl with timeouts and truncated output —
    huge log dumps would flood the model's context window."""
from __future__ import annotations

import json
import subprocess

from common.config import settings

KUBECTL_TIMEOUT_S = 20
MAX_OUTPUT_CHARS = 4000


def _kubectl(*args: str) -> str:
    cmd = ["kubectl", *args]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=KUBECTL_TIMEOUT_S
        )
    except FileNotFoundError:
        return json.dumps({"error": "kubectl not found on this machine"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"kubectl timed out after {KUBECTL_TIMEOUT_S}s",
                           "cmd": " ".join(cmd)})
    out = proc.stdout if proc.returncode == 0 else f"{proc.stdout}\n{proc.stderr}"
    out = out.strip()
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + f"\n...[truncated at {MAX_OUTPUT_CHARS} chars]"
    if proc.returncode != 0:
        return json.dumps({"error": f"kubectl exited {proc.returncode}", "output": out})
    return out


def register_ops_tools(mcp) -> None:
    ns = settings.kube_namespace

    @mcp.tool()
    def get_deployments(namespace: str = ns) -> str:
        """List Kubernetes deployments with their readiness (READY x/y, AGE).

        Start here to find unhealthy workloads: a deployment showing 0/1 READY
        has a problem worth diagnosing."""
        return _kubectl("get", "deployments", "-n", namespace, "-o", "wide")

    @mcp.tool()
    def get_pods(namespace: str = ns) -> str:
        """List pods with STATUS and RESTARTS.

        Look for CrashLoopBackOff, ImagePullBackOff, ErrImagePull, OOMKilled,
        Pending — then drill in with describe_pod / get_pod_logs."""
        return _kubectl("get", "pods", "-n", namespace, "-o", "wide")

    @mcp.tool()
    def describe_pod(pod: str, namespace: str = ns) -> str:
        """Full `kubectl describe` for one pod: container states, last
        termination reason and exit code, and the Events section — usually the
        single most informative view for a broken pod."""
        return _kubectl("describe", "pod", pod, "-n", namespace)

    @mcp.tool()
    def get_pod_logs(pod: str, namespace: str = ns, previous: bool = False,
                     tail: int = 100) -> str:
        """Read a pod's logs (tail N lines). Set previous=True to read the
        PREVIOUS crashed instance — essential for CrashLoopBackOff, where the
        current instance usually dies before logging anything."""
        args = ["logs", pod, "-n", namespace, f"--tail={tail}"]
        if previous:
            args.append("--previous")
        return _kubectl(*args)

    @mcp.tool()
    def get_events(namespace: str = ns, limit: int = 25) -> str:
        """Recent cluster events sorted by time: image pull failures, OOM
        kills, scheduling problems and probe failures all surface here."""
        out = _kubectl("get", "events", "-n", namespace,
                       "--sort-by=.lastTimestamp")
        lines = out.splitlines()
        return "\n".join(lines[-limit:]) if len(lines) > limit else out

    @mcp.tool()
    def rollout_restart(deployment: str, namespace: str = ns,
                        confirm: bool = False) -> str:
        """WRITE ACTION (gated): rolling-restart a deployment.

        Refuses unless confirm=True AND the operator started the server with
        COPILOT_ALLOW_WRITES=1. Propose this command in your report first and
        only call it when the human has explicitly approved."""
        if not settings.allow_writes:
            return json.dumps({
                "refused": "writes are disabled on this server "
                           "(operator must set COPILOT_ALLOW_WRITES=1)"})
        if not confirm:
            return json.dumps({
                "refused": "confirm=True is required to execute a write action; "
                           "propose the command to the operator first"})
        return _kubectl("rollout", "restart", f"deployment/{deployment}", "-n", namespace)
