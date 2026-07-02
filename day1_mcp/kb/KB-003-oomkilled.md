# Container OOMKilled (exit code 137)

**Category:** kubernetes | **Severity:** high | **Id:** KB-003

## Symptoms

Pod restarts with `Last State: Terminated, Reason: OOMKilled, Exit Code: 137` in
`kubectl describe pod`. Often looks like a CrashLoopBackOff (KB-001) from a distance.
Memory usage graphs show a sawtooth climbing to the limit before each restart.

## Diagnosis

1. Confirm the reason: `kubectl describe pod <pod> | grep -A3 "Last State"` → `OOMKilled`.
2. Compare actual usage to the limit: `kubectl top pod <pod>` (requires metrics-server) and
   the `resources.limits.memory` in the pod spec.
3. Distinguish two very different problems:
   - **Undersized limit**: steady-state usage is simply above the limit. The app is fine.
   - **Memory leak**: usage grows without bound over hours/days. The app is not fine.
4. For leaks, capture a heap profile or run the container locally under load.

## Resolution

- Undersized: raise `resources.limits.memory` (and `requests` accordingly) based on observed
  p99 usage + ~30% headroom, then `kubectl apply`.
- Leak: raising the limit only delays the kill. Fix the leak; as a stopgap, a scheduled
  rolling restart bounds the damage.
- Remember Kubernetes kills the container exceeding its limit even if the node has free
  memory — limits are a hard contract enforced by the kernel cgroup.

## Prevention

Set requests from real measurements not guesses, alert on container memory > 85% of limit,
and load-test memory behavior in CI for memory-sensitive services.
