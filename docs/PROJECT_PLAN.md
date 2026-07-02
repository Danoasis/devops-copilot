# DevOps Copilot — Agentic AI Triage System (Local-First Build Plan)

**One repo, one connected system, two job descriptions covered.**

An agentic assistant that triages IT/DevOps support tickets against a knowledge base of
runbooks, drafts grounded answers with citations, and can *act* on infrastructure (inspect
deployments, read pod logs, diagnose failures). It is built, shipped, and observed the way a
production system would be: CI/CD via Azure DevOps Pipelines, Infrastructure-as-Code in
Terraform and Bicep, containerized on Kubernetes, monitored with Prometheus + Grafana, and
evaluated with an LLM-as-judge harness.

**Everything runs on your machine.** LLM inference via Ollama, Kubernetes via kind, tracing via
Jaeger, metrics via Prometheus/Grafana in the cluster. Azure Pipelines runs for free on a
self-hosted agent (your own laptop registers as the build agent). Terraform/Bicep are written
against Azure but validated locally with `terraform plan` / `bicep build` — no spend required.

---

## How this maps to BOTH job descriptions

| Requirement | JD | Where it lives |
| --- | --- | --- |
| Agentic AI with modern frameworks | AI Engineer | `day2-agent/` — agent loop + MCP toolset |
| LLM integration & SDKs in production | AI Engineer | `day2-agent/`, `day3-service/` |
| Data pipelines for unstructured text | AI Engineer | `day2-agent/pipeline/` — chunk → embed → index |
| Async backend, databases, tracing | AI Engineer | `day3-service/` — FastAPI + SQLite + OpenTelemetry |
| Measurable AI outcomes (LLM-as-judge) | AI Engineer | `eval/` — scorecard with rubric-anchored judge |
| Azure DevOps Services (Pipelines, Repos, Artifacts, Boards) | Azure DevOps | `day4-devops/azure-pipelines.yml` + Boards/Repos workflow |
| CI/CD pipelines with Azure DevOps | Azure DevOps | Multi-stage pipeline: lint → test → build → deploy |
| IaC: Terraform, Bicep, ARM | Azure DevOps | `day4-devops/infra/terraform/` + `infra/bicep/` |
| Docker & Kubernetes | Both | `day3-service/Dockerfile`, `k8s/`, kind cluster |
| **Agentic AI tools to automate DevOps workflows** | Azure DevOps | `day5-agentic-ops/` — the agent's kubectl/log-analysis MCP tools |
| Monitoring/observability: Azure Monitor, App Insights, Prometheus, Grafana | Azure DevOps | `day4-devops/monitoring/` — kube-prometheus-stack + dashboards |
| Python / Bash / PowerShell scripting | Azure DevOps | Everywhere + pipeline scripts |
| AI-enthusiastic workflow (Claude Code, Gemini CLI, ...) | Azure DevOps (plus) | README section: how the repo was built with AI tooling |

The single strongest differentiator for the Azure DevOps JD is **Day 5**: the agent doesn't just
answer questions about DevOps — it *does* DevOps. It inspects a live (local) Kubernetes cluster,
reads failing pod logs, correlates them with runbooks, and proposes (or executes) a fix. That is
the "Demonstrated experience leveraging Agentic AI tools to automate DevOps workflows" line item,
demonstrated literally.

---

## Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │              Azure DevOps                    │
                        │  Repos ── Boards ── Pipelines ── Artifacts   │
                        │        (self-hosted agent = your laptop)     │
                        └──────────────┬───────────────────────────────┘
                                       │ CI: lint, test, docker build
                                       │ CD: kubectl apply to kind
                                       ▼
┌─────────────┐   HTTP    ┌────────────────────────┐   stdio/HTTP   ┌──────────────────┐
│   Client     │ ────────► │  FastAPI service        │ ─────────────► │  MCP server       │
│ (curl / UI)  │  /triage  │  (async, streaming)     │   tool calls   │  search_kb        │
└─────────────┘           │                          │                │  get_article      │
                          │  Agent loop              │                │  list_tickets     │
                          │  (Ollama via LiteLLM/    │                │  get_pod_logs     │
                          │   OpenAI-compat API)     │                │  get_deploy_status│
                          └────┬─────────┬───────────┘                └────────┬─────────┘
                               │         │                                     │
                     OTel traces         │ embeddings                          │ kubectl
                               ▼         ▼                                     ▼
                        ┌──────────┐  ┌─────────────────┐            ┌──────────────────┐
                        │  Jaeger   │  │ SQLite +         │            │  kind cluster     │
                        └──────────┘  │ sqlite-vec index │            │  Prometheus       │
                                      └─────────────────┘            │  Grafana          │
                                      (Ollama serves both            └──────────────────┘
                                       chat + embed models)
```

---

## Local stack (final decisions)

| Layer | Choice | Why |
| --- | --- | --- |
| Runtime | Python 3.11+, `uv` | Fast, lockfile, single tool for env + deps |
| LLM inference | **Ollama** | Fully local, OpenAI-compatible API at `http://localhost:11434/v1` |
| Chat model | `qwen2.5:7b` (or `llama3.1:8b`) | Both support **tool calling** in Ollama — non-negotiable for an agent |
| Embedding model | `nomic-embed-text` (768 dims) | Fast, solid quality, runs alongside the chat model |
| MCP | `mcp` Python SDK (FastMCP) | Official SDK, minimal boilerplate |
| Agent | Hand-rolled loop first → Google ADK via `LiteLlm(model="ollama_chat/qwen2.5")` | You must be able to whiteboard the loop; ADK shows framework fluency and matches the AI JD |
| Vector store | SQLite + `sqlite-vec` | Zero infra, one file, honest at this scale |
| Backend | FastAPI + Uvicorn | Async, streaming, the industry default |
| Tracing | OpenTelemetry → **Jaeger** (all-in-one container) | 100% local trace UI, one `docker run` |
| Metrics | Prometheus + Grafana (kube-prometheus-stack Helm chart) | Named explicitly in the Azure DevOps JD |
| Containers | Docker, multi-stage, non-root | Standard |
| Kubernetes | **kind** | Real K8s API on your laptop; what the pipeline deploys to |
| CI/CD | Azure DevOps Pipelines, **self-hosted agent** | Free tier: your machine runs the jobs, pipeline can reach your kind cluster |
| IaC | Terraform (primary) + Bicep (equivalent module) | JD asks for both; `plan`/`build` validate without spend |
| Eval | Custom `eval.py`, LLM-as-judge with rubric | "Measurable AI outcomes" |

> **Migrating from the Gemini build:** your Day 1 MCP server is untouched. In Day 2's
> `embedding.py`, swap `gemini-embedding-001` for Ollama's `/api/embed` with
> `nomic-embed-text`. Dimensions change (3072 → 768), so drop and rebuild the vector table —
> which your idempotent pipeline should treat as a normal full re-ingest. Keep the provider
> behind a small interface (`Embedder` protocol with `.embed(texts) -> list[list[float]]`) and
> switching becomes a config change; that abstraction is itself an interview talking point.

---

## Repo layout

```
devops-copilot/
├── README.md                  # architecture diagram, demo script, JD mapping (write LAST)
├── FUNDAMENTALS.md            # the coach document — your study backbone
├── pyproject.toml             # uv-managed, workspace root
├── day1-mcp/
│   ├── server.py              # FastMCP: search_kb, get_article, list_tickets + kb:// resource
│   └── kb/                    # markdown runbooks + sample tickets (unstructured corpus)
├── day2-agent/
│   ├── pipeline/
│   │   ├── ingest.py          # load → clean → chunk (with doc hashing for idempotency)
│   │   ├── embedding.py       # Embedder protocol: OllamaEmbedder (+ GeminiEmbedder kept)
│   │   └── index.py           # sqlite-vec schema, upsert, cosine search
│   └── agent/
│       ├── loop.py            # hand-rolled agent loop (understandable, whiteboardable)
│       ├── adk_agent.py       # same agent in Google ADK + LiteLLM → Ollama
│       └── schemas.py         # Pydantic: TriageResult(category, reply, citations, confidence)
├── day3-service/
│   ├── app/
│   │   ├── main.py            # POST /triage (async, streams), /healthz, /metrics
│   │   ├── telemetry.py       # OTel setup → Jaeger; prometheus_client metrics
│   │   └── store.py           # persist runs: ticket, answer, latency, tokens
│   ├── Dockerfile             # multi-stage, non-root
│   ├── compose.yaml           # api + ollama + jaeger for local dev
│   └── k8s/
│       ├── deployment.yaml    # + probes, resources, ConfigMap/Secret
│       ├── service.yaml
│       └── hpa.yaml
├── day4-devops/
│   ├── azure-pipelines.yml    # multi-stage: CI (lint/test/build/push) → CD (deploy to kind)
│   ├── scripts/               # pipeline helper scripts (bash + one PowerShell for the JD)
│   ├── infra/
│   │   ├── terraform/         # AKS + ACR + Log Analytics module (validated via plan)
│   │   └── bicep/             # equivalent Bicep — talk to the comparison
│   └── monitoring/
│       ├── prometheus-values.yaml
│       └── grafana-dashboard.json   # p50/p95 latency, tokens/s, error rate, judge score
├── day5-agentic-ops/
│   ├── ops_tools.py           # MCP tools: get_deploy_status, get_pod_logs, top_pods, rollout_restart
│   ├── incident_demo/         # a deliberately broken deployment (bad image tag / OOM)
│   └── diagnose.py            # agent workflow: detect → read logs → match runbook → propose fix
└── eval/
    ├── dataset.jsonl          # 10–20 labeled tickets
    ├── judge.py               # rubric-anchored LLM-as-judge (can use a bigger Ollama model)
    └── eval.py                # prints scorecard: accuracy, groundedness, p50/p95 latency
```

---

## Day-by-day

Days keep the original structure; Ollama-specific changes are marked. Days 4–5 are the new
Azure DevOps track. Each day: write the success-criteria checklist first (30 min), build the
happy path only, verify against the checklist and write 3 defensible talking points (30 min).

### Day 1 — MCP server *(done — one addition)*

As built: FastMCP server over stdio with `search_kb`, `get_article`, `list_tickets`, a
`kb://articles` resource, verified with MCP Inspector.

**Addition for the merged plan:** make sure the KB corpus is DevOps-flavored (runbooks for
"pod CrashLoopBackOff", "pipeline agent offline", "cert expiry", "disk pressure", ticket
samples referencing them). Your corpus is already IT/cloud — lean into it. This is what lets
Day 5 be spectacular.

### Day 2 — Data pipeline + agent *(in progress — Ollama swap lands here)*

**Part A — pipeline:** ingest → clean → chunk → embed → store in SQLite + sqlite-vec.
Idempotent via content hashing. `search_kb` upgrades from substring to semantic search.

- Ollama swap: `embedding.py` calls `POST http://localhost:11434/api/embed` with
  `model: nomic-embed-text`. Rebuild the index (768 dims).
- Keep the `Embedder` protocol so Gemini remains one env var away.

**Part B — agent:** hand-roll the loop first (`loop.py`): system prompt → model → if
`tool_calls` returned, execute against the MCP client, append results, repeat; terminate on a
final structured answer. Then reproduce it in ADK (`adk_agent.py`) with
`LiteLlm(model="ollama_chat/qwen2.5")` and the MCP toolset adapter. Task: triage a ticket →
search KB → structured `TriageResult` with citations. Real agency: if fewer than 2 citations
or confidence < threshold, refine the query and re-search (bounded to 3 iterations).

**Success criteria**
- [ ] Re-running ingest on unchanged corpus embeds 0 new chunks.
- [ ] `loop.py` answers a sample ticket end-to-end; tool-call trace printed.
- [ ] Output validates against the Pydantic model and includes real article ids.

### Day 3 — Async service, Docker, K8s

FastAPI `POST /triage` (async, **streams** tokens), persists each run (input, output, latency,
tokens) to SQLite. OpenTelemetry spans around the request → agent loop → each LLM call → each
MCP tool call, exported to Jaeger (`docker run jaegertracing/all-in-one`). Expose `/metrics`
with `prometheus_client` (request count, latency histogram, tokens counter).

Multi-stage `Dockerfile` (uv builder → slim runtime, non-root). `compose.yaml`: api + jaeger
(Ollama stays on the host; pass `OLLAMA_HOST=host.docker.internal`). Then kind: Deployment
(probes, resource requests/limits), Service, ConfigMap/Secret, HPA manifest.

**Success criteria**
- [ ] `curl -N localhost:8000/triage` streams a grounded answer.
- [ ] Jaeger shows one trace with nested LLM + tool spans.
- [ ] `kubectl get pods` shows the api Running in kind; port-forward works.

### Day 4 — Azure DevOps CI/CD + IaC + monitoring

**Pipelines:** create a free Azure DevOps org, push the repo to Azure Repos (or mirror from
GitHub), register your laptop as a **self-hosted agent** (free, and it can reach your kind
cluster). `azure-pipelines.yml`, multi-stage:

1. **CI stage** — jobs: `ruff` + `pytest` (unit tests for chunker, index, schemas); build the
   Docker image; push to a local registry (`kind` can load images directly:
   `kind load docker-image`); publish the eval dataset + k8s manifests as a **Pipeline
   Artifact**.
2. **CD stage** — depends on CI; environment `local-kind` with an approval check;
   `kubectl apply -k day3-service/k8s/` and wait for rollout; smoke test `POST /triage`.
3. **Eval stage (the flex)** — run `eval.py` against the deployed service and **publish the
   scorecard as a build artifact**; fail the pipeline if judge score drops below a threshold.
   That's "measurable AI outcomes" wired into CI/CD — both JDs in one sentence.

Use **Boards** honestly: create the work items for Days 4–5 as a small sprint, link commits
with `AB#123` so PRs close work items. Ten minutes of setup, and "hands-on with Boards/Repos"
becomes literally true and demonstrable.

**IaC:** `infra/terraform/` defining ACR + AKS + Log Analytics (remote-state stanza written but
commented for local). Validate with `terraform init/validate/plan` (plan works with a free
subscription without applying). `infra/bicep/` mirrors it; `az bicep build` compiles to ARM —
you can then speak to Terraform vs Bicep vs ARM concretely.

**Monitoring:** `helm install kube-prometheus-stack` into kind. Prometheus scrapes the api's
`/metrics` via a ServiceMonitor. Import `grafana-dashboard.json`: request rate, p50/p95
latency, error rate, tokens/s, eval score over time. Note the Azure Monitor / App Insights
mapping in the README (same concepts, managed flavor; `azure-monitor-opentelemetry` is a
one-line swap for the OTel exporter).

**Success criteria**
- [ ] Pipeline run is green end-to-end on the self-hosted agent; scorecard artifact downloadable.
- [ ] A commit with `AB#<id>` closes a Boards work item.
- [ ] `terraform plan` and `az bicep build` both succeed.
- [ ] Grafana dashboard shows live traffic from a smoke-test loop.

### Day 5 — Agentic DevOps automation (the differentiator)

Extend the MCP server with **ops tools** that shell out to `kubectl` against kind (read-only
by default): `get_deploy_status`, `get_pod_logs(pod, tail)`, `top_pods`, and one gated write
action `rollout_restart(deployment)` that requires an explicit `confirm=True`.

Break the cluster on purpose (`incident_demo/`: image tag typo → ImagePullBackOff, and a
memory-limit OOMKilled case). Then run `diagnose.py`: the agent lists deployments, spots the
unhealthy one, pulls logs/events, semantically matches them against your runbook KB, and
outputs a structured incident report — root cause, evidence (log lines + cited runbook),
recommended fix, and the exact command it *would* run. Optionally let it execute the gated
restart after human confirmation.

This is the demo you lead with for the Azure DevOps role: **an agent that automates a DevOps
workflow**, grounded, traced in Jaeger, deployed by Azure Pipelines, observed in Grafana.

**Success criteria**
- [ ] Agent correctly diagnoses both synthetic incidents with cited runbooks.
- [ ] Write actions are impossible without explicit confirmation (show the guardrail code).
- [ ] The full diagnosis appears as one trace in Jaeger.

---

## The 3-minute interview demo script

1. `git push` → Azure Pipeline fires on the self-hosted agent → green stages: CI → CD → Eval.
2. Open the eval **scorecard artifact**: accuracy, groundedness, p95 latency.
3. `kubectl delete` the good image tag, apply the broken one → pods go ImagePullBackOff.
4. `POST /triage` with "deployment X is down" → watch the stream: agent inspects the cluster,
   reads logs, cites the runbook, proposes the fix.
5. Show the whole thing as one Jaeger trace, then the Grafana dashboard ticking.
6. Close on the repo README: architecture diagram + JD mapping table.

For each component, have your crisp answer to: **why this, what's the tradeoff, what changes
at scale?** (FUNDAMENTALS.md ends every chapter with exactly those.)

---

## Open decisions to lock now

1. **Chat model:** `qwen2.5:7b` vs `llama3.1:8b` — pull both, run one ticket through each,
   keep the one that tool-calls more reliably on your hardware. (If RAM is tight, `qwen2.5:3b`
   still supports tools.)
2. **Judge model:** ideally a *different, larger* model than the agent's (e.g. judge with
   `qwen2.5:14b` if it fits, or keep Gemini's free tier just for judging — a defensible,
   honest choice you can explain: never let a model grade its own homework).
3. **ADK now or after:** recommended order is hand-rolled loop → ADK, so the framework never
   becomes a black box.
