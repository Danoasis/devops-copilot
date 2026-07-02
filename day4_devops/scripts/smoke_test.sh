#!/usr/bin/env bash
# Smoke test: is the deployed service alive and can it triage one ticket?
# Usage: smoke_test.sh http://localhost:18000
set -euo pipefail
BASE="${1:-http://localhost:8000}"

echo "[smoke] GET $BASE/healthz"
curl -fsS "$BASE/healthz" | grep -q '"ok"'

echo "[smoke] GET $BASE/readyz"
curl -fsS "$BASE/readyz" >/dev/null || {
  echo "[smoke] WARN: not ready (is Ollama reachable from the pod?)"; exit 1; }

echo "[smoke] POST $BASE/triage?stream=false"
RESPONSE=$(curl -fsS -X POST "$BASE/triage?stream=false" \
  -H 'Content-Type: application/json' \
  -d '{"ticket": "Pods for the checkout service keep restarting, kubectl shows CrashLoopBackOff and restarts climbing."}')

echo "$RESPONSE" | python3 -c '
import json, sys
data = json.load(sys.stdin)
result = data["result"]
assert result["category"], "missing category"
assert result["suggested_reply"], "missing reply"
print(f"[smoke] OK category={result[\"category\"]} "
      f"citations={result[\"citations\"]} latency_ms={data[\"latency_ms\"]}")'
