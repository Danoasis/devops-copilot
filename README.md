# DevOps Copilot

An agentic AI system that triages IT/DevOps support tickets and diagnoses live
Kubernetes incidents — grounded in a runbook knowledge base, exposed over MCP,
served by an async FastAPI backend, deployed to Kubernetes through an Azure
DevOps pipeline, observed with Prometheus/Grafana/OpenTelemetry, and gated by
an automated eval suite.

**Everything runs locally. Zero cloud spend.** LLM inference is Ollama on your
own machine; the cluster is `kind`; the Azure DevOps pipeline runs on a free
self-hosted agent; the Terraform/Bicep stacks are validated (`plan` /
`az bicep build`) without ever being applied.

Two companion documents live in [`docs/`](docs/):

* [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) — the build plan, decision log, and day-by-day map.
* [`docs/FUNDAMENTALS.md`](docs/FUNDAMENTALS.md) — a 12-chapter first-principles walkthrough of every technology in this repo (Ollama, MCP, RAG, agents, async Python, Docker, Kubernetes, Azure DevOps, Terraform/Bicep, observability, LLM evals). Read it if you want to understand *why* each piece exists, not just what it does.

---

## Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │              Azure DevOps Pipeline           │
                        │   CI (lint/test/build) → CD (kind deploy)    │
                        │           → Eval (quality gate)              │
                        └──────────────┬───────────────────────────────┘
                                       │ deploys
                                       ▼
 ticket ──► FastAPI service (day3) ──► agent loop (day2) ──► Ollama (qwen2.5:7b)
            /triage  SSE|JSON              │    ▲                local LLM
            /healthz /readyz /metrics      ▼    │ tool results
                    │                 MCP client (stdio)
                    │                      │
                    ▼                      ▼
            Prometheus + Grafana    MCP server (day1)
            OTel traces → Jaeger    ├── search_kb ──► sqlite-vec index ◄── ingest
                                    ├── get_article       (nomic-embed-text)
                                    ├── list_tickets
                                    └── ops tools (day5): kubectl read-only,
                                        writes double-gated
```

The agent is a **hand-rolled tool-calling loop** (`day2_agent/agent/loop.py`):
LLM proposes a tool call → client executes it via MCP → result goes back into
the conversation → repeat until the model emits a final JSON answer that
validates against a Pydantic schema. Bounded iterations, per-call timeouts,
one validation-repair retry, one quality-check nudge, OpenTelemetry spans on
every step. An optional [Google ADK](day2_agent/agent/adk_agent.py) variant
shows the same agent built on a framework instead.

## Repo layout

| Path | What it is |
|---|---|
| `day1_mcp/` | MCP server (FastMCP, stdio) + 8 runbook KB + sample tickets |
| `day2_agent/pipeline/` | Chunker → embeddings (Ollama / fake) → sqlite-vec index → idempotent ingest |
| `day2_agent/agent/` | Agent loop, MCP client, Pydantic schemas, CLI, optional ADK variant |
| `day3_service/` | Async FastAPI service (SSE streaming, health/readiness, Prometheus metrics, OTel), Dockerfile, compose, K8s manifests |
| `day4_devops/` | Azure DevOps multi-stage pipeline, smoke tests, Terraform + Bicep (AKS/ACR/Log Analytics), kube-prometheus-stack values, ServiceMonitor, Grafana dashboard |
| `day5_agentic_ops/` | kubectl MCP tools (read-only by default, writes double-gated), incident diagnosis agent, two reproducible synthetic incidents |
| `evals/` | Labeled dataset, LLM-as-judge, `copilot-eval` quality gate |
| `tests/` | Unit + integration tests (no Ollama required — fake embedder) |

## Quickstart

Prereqs: Python 3.12+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com).

```bash
# 1. Pull local models (~5 GB total)
ollama pull qwen2.5:7b          # chat model with tool calling
ollama pull nomic-embed-text    # embedding model (768-dim)

# 2. Install
uv sync                          # add --extra adk for the Google ADK variant

# 3. Build the vector index from the runbooks
uv run copilot-ingest            # add --rebuild to force re-embedding
                                 # add --fake for a no-Ollama test index

# 4. Triage a ticket from the terminal (agent trace on stderr, JSON on stdout)
uv run copilot-triage "checkout-api pods keep restarting, exit code 137, \
  kubectl describe says OOMKilled"

# 5. Run the service
uv run uvicorn day3_service.app.main:app --port 8000
curl -N -X POST 'localhost:8000/triage?stream=true' \
  -H 'content-type: application/json' \
  -d '{"ticket": "terraform pipeline fails with state lock error"}'
```

### Tests and lint (no Ollama needed)

```bash
uv run pytest          # 23 tests: chunker, sqlite-vec index, ingest, schemas, eval helpers
uv run ruff check .
```

The tests use a deterministic fake embedder against the **real** sqlite-vec
storage path, so CI exercises everything except the LLM itself.

### Docker & Kubernetes (kind)

```bash
# Compose: service + Jaeger for traces (Ollama stays on the host)
docker compose -f day3_service/compose.yaml up --build
# traces at http://localhost:16686

# kind: build once, side-load the image, apply manifests
docker build -t devops-copilot:local -f day3_service/Dockerfile .
kind create cluster --config day4_devops/scripts/kind-config.yaml
kind load docker-image devops-copilot:local
kubectl apply -k day3_service/k8s/
kubectl rollout status deploy/devops-copilot
```

### Monitoring

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install kps prometheus-community/kube-prometheus-stack \
  -f day4_devops/monitoring/prometheus-values.yaml
kubectl apply -f day4_devops/monitoring/servicemonitor.yaml
# import day4_devops/monitoring/grafana-dashboard.json into Grafana
# (request rate by outcome, p50/p95 latency, tokens/min, in-flight, error rate)
```

### Azure DevOps pipeline

`day4_devops/azure-pipelines.yml` — three stages on a free **self-hosted
agent** (your own machine, registered in an agent pool):

1. **CI** — ruff, pytest, fake-embedder ingest smoke, Docker image build
   (tagged with the commit SHA, never `:latest`).
2. **CD** — deployment job against a `local-kind` environment (approval-gated),
   `kind load` the image, `kubectl apply -k` + `rollout status` as the deploy
   gate, then an HTTP smoke test through a port-forward.
3. **Eval** — `copilot-eval` runs the labeled dataset against the deployed
   service and **fails the pipeline** if quality thresholds aren't met. A
   PowerShell step publishes the scorecard as a build artifact.

The IaC in `day4_devops/infra/` defines the equivalent Azure footprint (AKS +
ACR + Log Analytics, AcrPull via managed identity) twice — once in Terraform,
once in Bicep — and both are validated in CI without applying:

```bash
cd day4_devops/infra/terraform && terraform init -backend=false && terraform validate
az bicep build --file day4_devops/infra/bicep/main.bicep
```

### Day 5: agentic incident diagnosis

```bash
# Create a reproducible incident (ImagePullBackOff or OOMKilled)
kubectl apply -f day5_agentic_ops/incident_demo/broken-image.yaml

# Let the agent investigate: deployments → pods → describe → previous logs
# → events → search the KB → propose (never execute) a fix
COPILOT_ENABLE_OPS_TOOLS=1 uv run copilot-diagnose web-frontend
```

The kubectl tools are **read-only by default**. The single write tool
(`rollout_restart`) is double-gated: the operator must export
`COPILOT_ALLOW_WRITES=1` *and* the agent must pass `confirm=true`. Bounded
autonomy is the design stance: the agent gathers evidence and proposes; the
human executes.

### Evals as a quality gate

```bash
uv run copilot-eval --endpoint http://localhost:8000 --out scorecard.json
uv run copilot-eval --skip-judge     # deterministic layer only (CI-friendly)
```

Two layers. Deterministic checks catch what code can catch exactly: schema
validity, citation integrity (every cited runbook must exist — a fabricated id
is a hallucination caught for free), category accuracy against labels, and
honesty on two "trap" tickets whose only correct answer is
`needs_escalation`. The LLM-as-judge layer then scores groundedness,
correctness, and helpfulness against rubric anchors (0 / 0.5 / 1), reading the
**full text of the cited runbooks** so it grades against the evidence, not its
own opinions. Set `JUDGE_MODEL` to a different model than the agent — never
let a model grade its own homework. Thresholds (`EVAL_MIN_ACCURACY`,
`EVAL_MIN_GROUNDEDNESS`, ...) come from env; below threshold the process exits
non-zero, which is what turns a scorecard into a deploy gate.

## Configuration

Copy `.env.example` and adjust. Everything is env-driven (`common/config.py`):
`OLLAMA_BASE_URL`, `CHAT_MODEL`, `EMBED_MODEL`, `JUDGE_MODEL`, `COPILOT_DB`,
`MAX_AGENT_ITERATIONS`, `LLM_TIMEOUT_S`, `COPILOT_ENABLE_OPS_TOOLS`,
`COPILOT_ALLOW_WRITES`, `OTEL_EXPORTER_OTLP_ENDPOINT`.

## Design decisions worth asking me about

* **Why a hand-rolled agent loop before a framework?** Because the loop *is*
  the concept: ~200 lines make tool calling, bounded iteration, repair
  retries, and tracing completely legible. The ADK variant then shows the
  same shape through a framework's lens.
* **Why sqlite-vec instead of a vector DB service?** One file, zero infra,
  transactional with the chunk metadata, and it pins `(embed_model, dim)` so
  mixing vector spaces fails loudly instead of corrupting search silently.
* **Why does ingest reconcile instead of append?** Same reason
  `kubectl apply` reconciles: re-running must converge to the source of
  truth. Unchanged files are hash-skipped; deleted files are removed.
* **Why is the readiness probe different from the liveness probe?** Liveness
  answers "is the process alive" (restart if not); readiness answers "can I
  serve" (checks Ollama reachability, gates traffic). Conflating them causes
  restart storms during dependency outages.
* **Why is the judge a different model?** Self-grading correlates errors:
  the same blind spot produces the mistake and forgives it.
* **Why traps in the eval set?** An agent that answers everything is worse
  than one that escalates honestly. EV-11/EV-12 have no covering runbook;
  the only passing answer is `needs_escalation` with zero citations.

## License

MIT — use anything here for your own learning or interviews.
