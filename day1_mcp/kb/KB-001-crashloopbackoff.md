# Pod stuck in CrashLoopBackOff

**Category:** kubernetes | **Severity:** high | **Id:** KB-001

## Symptoms

A pod repeatedly starts and exits. `kubectl get pods` shows STATUS `CrashLoopBackOff` and a
climbing RESTARTS count. The backoff delay doubles after each crash (10s, 20s, 40s ... capped
at 5m), so the pod spends most of its time waiting to be restarted.

## Diagnosis

1. Read the logs of the *previous* container instance, not the current one:
   `kubectl logs <pod> --previous` — the current instance usually dies before logging anything.
2. Check the last state and exit code: `kubectl describe pod <pod>` and look at
   `Last State: Terminated / Exit Code`.
   - Exit code 1: application error — read the stack trace in the logs.
   - Exit code 137: the container was SIGKILLed, almost always OOMKilled (see KB-003).
   - Exit code 127 or "exec format error": bad command, missing binary, or wrong CPU arch image.
3. Check recent events: `kubectl get events --sort-by=.lastTimestamp | tail -20`.
4. If the container dies instantly with no logs, the entrypoint itself is broken: verify the
   image CMD/ENTRYPOINT and any command/args overrides in the Deployment.

## Resolution

- Application bug: fix the code, build a new image tag, roll out. Never patch inside the pod.
- Missing config/secret: crash logs typically show a KeyError or "connection refused" to a
  dependency. Verify ConfigMap/Secret keys mounted as env vars match what the app expects.
- Failing liveness probe killing a slow-starting app: increase `initialDelaySeconds` or use a
  `startupProbe`; a liveness probe that checks a dependency causes restart storms.
- Roll back fast if a new release introduced it: `kubectl rollout undo deployment/<name>`.

## Prevention

Readiness and liveness probes tuned per service, resource limits reviewed against real usage,
and a CI smoke test that starts the container once before deploy.
