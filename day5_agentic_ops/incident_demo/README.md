# Incident demo

Break the cluster on purpose, then watch the agent diagnose it.

```bash
kubectl apply -f day5_agentic_ops/incident_demo/broken-image.yaml
kubectl apply -f day5_agentic_ops/incident_demo/oom-demo.yaml
sleep 30   # let the failures develop

COPILOT_ENABLE_OPS_TOOLS=1 uv run copilot-diagnose
```

Expected: an `IncidentReport` naming the broken deployment, quoting the
ImagePullBackOff / OOMKilled evidence, citing KB-002 / KB-003, and proposing the
exact fix command — without executing anything.

Clean up: `kubectl delete deploy web-frontend report-worker`
