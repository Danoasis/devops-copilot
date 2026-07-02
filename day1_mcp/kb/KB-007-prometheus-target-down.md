# Prometheus target down / metrics missing in Grafana

**Category:** observability | **Severity:** medium | **Id:** KB-007

## Symptoms

Grafana panels show "No data"; Prometheus UI → Status → Targets shows the scrape target as
DOWN with an error (connection refused, context deadline exceeded, or 404 on /metrics).
Alert `up == 0` may be firing.

## Diagnosis

1. Identify how the target is discovered. With kube-prometheus-stack, apps are scraped via a
   `ServiceMonitor`: it must (a) live in a namespace Prometheus watches, (b) have labels
   matching the Prometheus `serviceMonitorSelector` (commonly `release: <helm-release-name>`),
   and (c) select the Service by label with the right port *name*.
2. `kubectl port-forward svc/<app> 8000:8000` then `curl localhost:8000/metrics` — does the
   app actually expose metrics? A 404 means the app; a refused connection means the Service
   or the port name mapping.
3. Check Prometheus logs for scrape errors and the `prometheus_sd_discovered_targets` count —
   zero discovered targets means the selector chain is broken, not the app.

## Resolution

- Missing label on the ServiceMonitor (the classic): add `release: kube-prometheus-stack`
  (or your Helm release name) to the ServiceMonitor metadata labels.
- Port mismatch: ServiceMonitor `endpoints[].port` must equal the Service's port **name**
  (e.g. `http`), not the number.
- App not instrumented: expose `/metrics` (prometheus_client) and ensure the Service targets
  that container port.

## Prevention

A meta-alert on `up == 0` and on `absent(<key_metric>)` for critical series; a smoke check in
CD that curls /metrics after rollout.
