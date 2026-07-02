# FUNDAMENTALS — The Coach Document

This is the backbone of your understanding of the DevOps Copilot project. It teaches the
*fundamentals* of every tool and concept in the build, in the order you'll meet them. Each
chapter follows the same shape:

1. **The mental model** — the one idea that makes everything else obvious.
2. **Why it exists** — what problem it solves and what people did before it.
3. **The core concepts** — the vocabulary you must own cold.
4. **In this project** — exactly where and how you use it.
5. **Interview drill** — the questions you will be asked, with the shape of a strong answer,
   always ending in: *why this, what's the tradeoff, what changes at scale?*

How to use it: read a chapter *before* building that part. Then build. Then come back and
re-read the interview drill and try to answer out loud without looking. If you can't explain
it to an imaginary junior engineer, you don't own it yet.

---

## Chapter 1 — Local LLMs with Ollama

### The mental model

Ollama is **Docker for language models**. It's a runtime daemon that pulls model weights from
a registry (`ollama pull qwen2.5:7b`), loads them into RAM/VRAM, and exposes them over a local
HTTP API. Your application never touches the weights; it just makes HTTP calls to
`localhost:11434`, exactly as it would call OpenAI or Gemini — the model became a service.

### Why it exists

Running a raw model checkpoint yourself means: downloading tens of GB of weights, choosing an
inference engine (llama.cpp, vLLM), compiling it for your GPU/CPU, writing a serving layer,
and managing prompt templates that differ per model family. Ollama packages all of that:
weights + quantization + prompt template + parameters travel together in a **Modelfile**
(deliberately analogous to a Dockerfile), and the daemon handles loading, unloading, and
concurrent requests.

### Core concepts

**Quantization.** Model weights are natively 16-bit floats. A 7B-parameter model at fp16 is
~14 GB — too big for most laptops. Quantization stores weights at lower precision (8-bit,
4-bit), trading a small quality loss for a 2–4× memory cut. The default Ollama tags (like
`qwen2.5:7b`) are 4-bit quantized (~4.7 GB), which is why a 7B model fits on your machine at
all. Rule of thumb: 4-bit needs roughly `params × 0.6` GB of memory plus room for context.

**Context window.** The model's working memory in tokens. Everything — system prompt, tool
definitions, conversation history, retrieved chunks — must fit inside it. Ollama defaults to a
small context (often 4k) to save memory; for agents with tools and retrieved docs you'll
raise it (`num_ctx`), paying RAM for it. This is why chunking (Chapter 3) exists: you retrieve
only the *relevant* slices of your corpus into that limited window.

**The two APIs.** Ollama exposes its native API (`/api/chat`, `/api/embed`) and an
**OpenAI-compatible** API (`/v1/chat/completions`). The compatible endpoint is why almost any
framework (LiteLLM, the `openai` Python client, ADK-via-LiteLLM) can talk to Ollama by just
changing `base_url`. This idea — *the OpenAI API shape as the de-facto standard interface* —
is a genuinely important piece of industry context.

**Tool calling.** The model doesn't "run" tools. You send it a list of tool schemas (name,
description, JSON parameters); if the model decides a tool is needed, it replies with a
structured `tool_calls` message instead of prose. *Your code* executes the tool and sends the
result back as a `tool` role message; the model then continues. Not every model is trained to
emit this structure — that's why the chat model choice (`qwen2.5`, `llama3.1`) is
non-negotiable for this project, and a random model tag might silently break your agent.

**Embedding models are separate models.** `nomic-embed-text` doesn't chat; it maps text to a
768-dimensional vector. Ollama serves both kinds side by side.

### In this project

- `ollama serve` runs as your local model backend for *everything*: agent chat, embeddings,
  and (optionally) the eval judge.
- `embedding.py` calls `POST /api/embed` with `nomic-embed-text`.
- The agent talks to `http://localhost:11434/v1` via the OpenAI client (hand-rolled loop) or
  via `LiteLlm(model="ollama_chat/qwen2.5")` (ADK).
- Containers reach the host's Ollama through `host.docker.internal:11434`; pods in kind reach
  it via your host IP passed in a ConfigMap. (Alternative: run Ollama itself as a container —
  fine, but slower without GPU passthrough; know both options.)

### Interview drill

- *"Why local models instead of an API?"* — Data privacy (nothing leaves the machine), zero
  marginal cost, no rate limits, offline demos. Tradeoffs: smaller models are less capable,
  you own the hardware constraints, and you lose provider-managed safety/scaling. Strong
  answer: "I abstracted the provider behind an interface, so local Ollama for dev and a hosted
  model for prod is a config change" — then show the `Embedder` protocol.
- *"What's quantization and what does it cost you?"* — Precision reduction for memory;
  slight quality degradation, usually acceptable at 4-bit for 7B+ models.
- *"At scale?"* — Ollama is a dev/single-node tool. Production local inference means vLLM or
  TGI: continuous batching, paged attention (paged KV cache), tensor parallelism across GPUs.
  Naming vLLM and *why* (throughput via continuous batching) is a senior-level signal.

---

## Chapter 2 — MCP (Model Context Protocol)

### The mental model

MCP is **USB-C for AI tools**. Before it, every agent framework had its own way to define
tools, so a "search my KB" tool written for one framework couldn't be used by another. MCP
standardizes the plug: a **server** exposes tools/resources/prompts in a standard schema; any
**client** (Claude Desktop, an ADK agent, your own loop) can discover and call them. Write the
tool once, plug it into anything.

### Why it exists

Tool integrations were N×M: N frameworks × M services, each pair hand-wired. MCP collapses it
to N+M — each framework implements the client side once, each service implements the server
side once. It's the same argument as the LSP (Language Server Protocol) for editors, which is
its explicit inspiration.

### Core concepts

**The three primitives:**

- **Tools** — functions the *model* decides to call (`search_kb(query)`). Model-controlled;
  they can have side effects.
- **Resources** — data the *application* attaches to context (`kb://articles`). Think GET
  endpoints: read-only, addressed by URI, no side effects. The host/user chooses to load them;
  the model doesn't "call" them.
- **Prompts** — reusable, user-invoked prompt templates (slash-command-shaped).

The tools-vs-resources distinction is a favorite interview probe. The crisp answer: *who
controls the invocation* (model vs application) and *side effects* (allowed vs none).

**Transports.** MCP is JSON-RPC 2.0 messages over some pipe:

- **stdio** — client launches the server as a subprocess, messages flow over
  stdin/stdout. Zero networking, perfect for local/desktop. Limitation: client and server
  share a machine, one client per server process.
- **Streamable HTTP (with SSE for server→client streaming)** — the server is a real network
  service; multiple remote clients. Needed the moment your backend runs in Kubernetes and the
  MCP server runs elsewhere.

**Lifecycle.** Client connects → `initialize` handshake (capability negotiation) → client
calls `tools/list` to *discover* what exists → then `tools/call` as needed. Discovery is the
point: the client hard-codes nothing.

**FastMCP** is the high-level Python SDK API: decorate a function with `@mcp.tool()`, and its
signature + docstring become the JSON schema the model sees. **That makes docstrings and type
hints part of your prompt engineering** — a vague description produces a model that misuses
your tool.

### In this project

- `day1-mcp/server.py` exposes `search_kb`, `get_article`, `list_tickets` over stdio, plus
  the `kb://articles` resource.
- Day 2: `search_kb`'s internals swap from substring matching to the semantic index — the
  *contract stays identical*, which is exactly the decoupling MCP promises. Say that sentence
  in the interview.
- Day 5 adds ops tools (`get_pod_logs`, `rollout_restart`) — same server pattern, now with a
  side-effect guardrail (`confirm=True` required for writes).
- MCP Inspector (`npx @modelcontextprotocol/inspector`) is your test harness: it's just a
  generic client, which proves interoperability.

### Interview drill

- *"Tools vs resources?"* — Control + side effects (above).
- *"Why MCP instead of the framework's native tool definitions?"* — Portability (same server
  works from Claude Desktop, ADK, or a custom loop), separation of concerns (tool authors vs
  agent authors), and an emerging ecosystem standard. Tradeoff: extra process + protocol hop
  for tools only one app will ever use; for a single in-process tool, a plain function is
  simpler.
- *"stdio vs HTTP?"* — Locality vs reachability. stdio: no network surface, trivially secure,
  single-client. HTTP: multi-client, deployable, but now you own auth, TLS, and availability.
- *"At scale?"* — MCP servers become microservices: HTTP transport, containerized, per-tool
  authz, rate limiting, and their spans stitched into your traces (Chapter 9).

---

## Chapter 3 — Embeddings, Chunking, and Vector Search (the RAG pipeline)

### The mental model

An embedding model is a function that maps text to a point in space such that **distance means
meaning**. "The pod keeps restarting" and "container in CrashLoopBackOff" land near each other
in that 768-dimensional space even though they share almost no words. Semantic search is then
just geometry: embed the query, find the nearest stored points.

### Why it exists

Keyword search (your Day 1 substring `search_kb`) fails on vocabulary mismatch — users say
"app is down", runbooks say "service unavailable". Embeddings solve the *synonym problem*
structurally instead of by maintaining synonym lists. And retrieval as a whole exists because
of the context window: you can't stuff the entire KB into the prompt, so you fetch only the
top-k relevant slices. That pattern — retrieve, then generate an answer *grounded* in what was
retrieved — is RAG (Retrieval-Augmented Generation).

### Core concepts

**Cosine similarity.** The standard closeness measure: the cosine of the angle between two
vectors — 1.0 means same direction (same meaning), 0 means unrelated. Used instead of raw
distance because it ignores vector length, and most embedding models are trained/normalized
for it. When vectors are normalized to unit length, cosine similarity and dot product are the
same operation — that's why you'll see both terms used interchangeably.

**Chunking.** Documents are too long to embed as one vector — a 5-page runbook averaged into
a single point loses all local detail ("dilution"), and retrieved context should be small
anyway. So you split documents into chunks and embed each. The tradeoff triangle:

- Too small → chunks lack context to be understood alone ("restart it" — restart *what*?).
- Too large → dilution + wasted context window.
- The pragmatic default: split on natural structure first (markdown headers — your runbooks
  have them), target roughly 300–800 tokens, and add ~10–15% overlap between adjacent chunks
  so sentences at boundaries aren't orphaned.

Chunking is where most RAG quality is won or lost, and interviewers know it. Being able to say
"I chunked on markdown headers because runbook sections are semantically self-contained, and I
kept the section title prepended to every chunk for context" is a *much* stronger answer than
naming a fancy vector database.

**The pipeline shape.** `load → clean → chunk → embed → upsert`. Two production properties:

- **Idempotency**: hash each document's content; skip unchanged docs on re-run. Re-running the
  pipeline twice must be safe and cheap. (Same property you demand of Terraform and of
  `kubectl apply` — say that out loud in a DevOps interview, it lands.)
- **Determinism/versioning**: record the embedding model name + dimensions with the index.
  Vectors from different models are incomparable — mixing them is a classic silent failure.
  This is exactly why your Gemini→Ollama swap forces a full re-embed (3072-dim and 768-dim
  vectors don't live in the same space, or the same table).

**Vector storage.** At your scale (hundreds of chunks), brute-force cosine over a SQLite table
is *fast* and honest — `sqlite-vec` gives you a virtual table and a `MATCH` query, zero infra.
Approximate-nearest-neighbor indexes (HNSW — the graph-based index used by pgvector, Qdrant,
etc.) exist because brute force is O(N) per query; they trade a little recall for sub-linear
search once N reaches millions. Knowing *when you don't need them* is the senior signal.

**Grounding and citations.** The retrieved chunks go into the prompt with their article ids;
the agent's answer must cite them. Grounding is your hallucination control: the model is
instructed to answer *from the provided context or say it can't*, and citations make that
auditable. Your eval (Chapter 10) scores exactly this.

### In this project

- `pipeline/ingest.py` — walk `kb/`, hash, clean, chunk on headers.
- `pipeline/embedding.py` — `Embedder` protocol; `OllamaEmbedder` posts to `/api/embed`
  (`nomic-embed-text`, 768 dims), batching texts per request.
- `pipeline/index.py` — sqlite-vec table `(chunk_id, article_id, heading, text, embedding)`;
  `search(query, k)` embeds the query and returns top-k with distances.
- Day 1's `search_kb` now calls `index.search` — MCP contract unchanged.

### Interview drill

- *"Walk me through your data pipeline for unstructured text."* — Load/clean/chunk/embed/
  upsert, hashing for idempotency, model+dims versioned with the index, re-runnable. That
  sentence *is* the JD line item.
- *"How did you pick chunk size?"* — Structure-first (headers), then a token budget; explain
  both failure modes (dilution vs orphaned fragments) and the overlap fix.
- *"Why SQLite and not Pinecone/Qdrant?"* — Right-sizing: brute force is exact and instant at
  this N; a managed ANN index adds infra and approximation for zero benefit here. At scale:
  pgvector or a dedicated store, HNSW, filtered search, and re-ranking (retrieve 50 with
  vectors, re-rank to 5 with a cross-encoder).
- *"Semantic search misses an obvious keyword match — what do you do?"* — Hybrid search:
  combine BM25 (keyword) and vector scores. Embeddings are weak on exact identifiers (error
  codes, hostnames); keyword search is weak on paraphrase. Production RAG usually runs both.

---

## Chapter 4 — Agents and Tool Calling

### The mental model

An agent is a **while loop around an LLM**: the model sees a goal and a set of tools; each
iteration it either *acts* (emits a tool call) or *answers*. Your code executes the actions,
feeds results back, and the loop continues until an answer or an iteration cap. Everything
else — frameworks, "multi-agent systems", orchestration — is elaboration on that loop.

```
messages = [system, user_ticket]
for _ in range(MAX_ITERS):
    reply = llm(messages, tools)
    if reply.tool_calls:
        for call in reply.tool_calls:
            result = mcp_client.call(call.name, call.args)
            messages.append(tool_result(call.id, result))
    else:
        return parse_structured(reply)   # Pydantic-validated TriageResult
```

If you can write that from memory on a whiteboard and narrate every line, you pass the
"agentic AI" portion of any interview. That's why you build `loop.py` by hand before touching
ADK.

### Why it exists

A single LLM call is a pure function: text in, text out, frozen knowledge, no side effects.
Real tasks need current data (search the KB, read pod logs) and multiple dependent steps
(search → read → decide → maybe search again). Tool calling gives the model hands; the loop
gives it more than one move.

### Core concepts

**Workflow vs agent.** A *workflow* is control flow **you** hard-coded (always: retrieve →
generate → format). An *agent* lets the **model** choose the control flow (which tool, when to
stop, whether to retry). The design question is always: how much freedom does the model need?
Freedom buys flexibility and costs predictability, latency, and debuggability. Your triage
system is deliberately a hybrid: the outer shape is fixed (triage a ticket, return
`TriageResult`), but tool selection and the low-confidence re-query are the model's choice —
bounded by an iteration cap. Being able to articulate *where you put the boundary and why* is
the senior answer.

**The ReAct pattern.** Reason → Act → Observe, repeated: the model reasons about what it
knows, acts (tool call), observes the result, reasons again. Modern native tool-calling is
ReAct with the "act" step made structural instead of parsed from prose.

**Structured output.** Never let an agent's final answer be free prose if a machine consumes
it. Define a Pydantic model (`TriageResult: category, suggested_reply, citations,
confidence`), instruct the model to emit JSON matching it, validate, and **feed validation
errors back to the model for one retry** — that error-repair loop is a production pattern
worth mentioning by name.

**Guardrails.** Iteration caps (agents loop forever), tool timeouts, and side-effect gating
(Day 5's `rollout_restart(confirm=True)`, plus human approval before execution). The phrase
"read-only by default, writes gated behind explicit confirmation" is precisely what "agentic
AI in DevOps" interviewers are probing for — an agent with `kubectl` is a loaded weapon, and
they want to hear that you know it.

**Context management.** Every loop iteration appends messages; tool results can be huge (pod
logs!). Truncate/summarize tool outputs before appending (e.g. tail 200 lines, or extract
error lines), or the context window fills and quality collapses. This tiny detail separates
people who've built agents from people who've read about them.

**Frameworks (ADK).** Google's Agent Development Kit gives you the loop, session state,
tool adapters (including an MCP toolset), and eval hooks. Under the hood it's the same loop.
`LiteLlm(model="ollama_chat/qwen2.5")` routes ADK's model calls through LiteLLM to your local
Ollama — LiteLLM being a translation layer that speaks the OpenAI shape to ~anything.

### In this project

- `agent/loop.py` — the hand-rolled loop above, OpenAI client pointed at Ollama, MCP client
  session for tools, `TriageResult` validation with one repair retry.
- `agent/adk_agent.py` — same behavior in ADK with the MCP toolset; you get session handling
  and a path to ADK's eval tooling.
- The "real agency" beat: if `len(citations) < 2 or confidence < 0.6`, the agent reformulates
  the query and searches again (max 3 total attempts).
- Day 5's `diagnose.py` reuses the identical loop with ops tools — one architecture, two
  demos.

### Interview drill

- *"Design an agent for X"* — Draw the loop. Then immediately talk about boundaries: which
  decisions the model owns, which you hard-code, caps, timeouts, structured output, write
  gating.
- *"When would you NOT use an agent?"* — When the control flow is known in advance: a fixed
  RAG pipeline is cheaper, faster, and deterministic. Agents earn their cost when the path
  varies per input. Volunteering this tradeoff unprompted is a strong signal.
- *"How do you debug an agent?"* — Traces (Chapter 9): every LLM call and tool call is a span
  with inputs/outputs; you replay the trajectory. "I don't debug agents with print statements,
  I debug them with traces" is the line.
- *"At scale?"* — Concurrency (async, Chapter 5), caching repeated tool results, model routing
  (small model for routine tickets, big model for hard ones), and evals as regression tests on
  every change (Chapter 10).

---

## Chapter 5 — Async Python and FastAPI

### The mental model

Async is **single-threaded cooperative multitasking for waiting**. One thread runs an event
loop; whenever a task reaches an `await` on I/O (an LLM call, a DB read), it yields, and the
loop runs someone else's ready work. Nothing computes in parallel — instead, nobody blocks the
thread while *waiting*. Since an LLM app is overwhelmingly waiting (a 7B model takes seconds
per answer; your Python does microseconds of work around it), async is the natural shape: one
process can hold hundreds of in-flight requests open concurrently.

The restaurant analogy that actually holds: sync-with-threads is one waiter per table; async
is one waiter serving every table, taking the next order while kitchens (LLM, DB) cook.

### Why it exists

The classic sync model handles concurrency with threads/processes — heavy (memory per thread,
context switches) and capped. For I/O-bound servers, the event-loop model (nginx, Node.js)
proved you can hold thousands of connections cheaply. `async`/`await` brought that to Python
with readable, sequential-looking code.

### Core concepts

**`async def` / `await`.** An `async def` function returns a coroutine — a pausable
computation. `await` marks the pause points. Key rule: `await` only things that are actually
async; calling a *blocking* function (e.g. the sync `requests` library, or heavy CPU work)
inside an async handler freezes the entire event loop — every request stalls. Fixes: use async
clients (`httpx.AsyncClient` for Ollama), or push blocking/CPU work off the loop with
`asyncio.to_thread(...)`. "What happens if you block the event loop?" is a top-three async
interview question.

**Concurrency combinators.** `asyncio.gather(*tasks)` runs awaitables concurrently (embed all
chunks of a batch at once); `asyncio.wait_for(task, timeout)` enforces timeouts — every
network call in production gets one.

**Streaming.** LLMs generate token by token; waiting 20 s for a full answer feels broken while
the same 20 s streamed feels alive. Two mechanics: the model API streams chunks to you
(`stream=True`), and you re-stream them to the client — in FastAPI, return a
`StreamingResponse` wrapping an async generator, typically as SSE (Server-Sent Events:
`text/event-stream`, lines of `data: ...`). Note the symmetry: SSE is the same mechanism MCP's
HTTP transport uses for server→client messages.

**FastAPI specifics.** Routes declared `async def` run on the event loop (never block them!);
plain `def` routes are automatically run in a threadpool — a safe harbor for sync code.
Pydantic models double as request/response validation and OpenAPI docs (`/docs` for free).
Dependency injection (`Depends`) wires shared resources (DB, the agent) into handlers.
Lifespan handlers (startup/shutdown) are where you create the shared `httpx` client and open
the MCP session once, not per request. Uvicorn is the ASGI server that runs it all — ASGI
being the async successor to WSGI, the interface between server and framework.

**Backpressure, timeouts, retries.** What happens when requests arrive faster than the LLM
can answer? Unbounded queues die slowly; a `asyncio.Semaphore(N)` around agent runs caps
concurrent LLM work, and beyond that you return 429/queue. Retries on LLM calls: only on
transient failures, with exponential backoff + jitter, and idempotency in mind. These three
words — backpressure, timeout, retry — are the reliability vocabulary of the whole interview.

### In this project

- `app/main.py`: `POST /triage` is an `async def` that runs the agent and returns a
  `StreamingResponse` (SSE) of tokens, then a final structured JSON event.
- `httpx.AsyncClient` for Ollama; MCP session opened in lifespan; `Semaphore` caps concurrent
  triages; `wait_for` timeouts on every model/tool call.
- `store.py` persists each run (ticket, answer, latency, token counts) — the raw material for
  both your metrics and your eval set.
- `/healthz` (liveness/readiness for K8s) and `/metrics` (Prometheus) round out the
  production shape.

### Interview drill

- *"Async vs threads vs processes?"* — I/O-bound + many connections → async. CPU-bound →
  processes (the GIL blocks thread parallelism for pure Python CPU work). Blocking libraries
  you can't replace → threads. One sentence each, then map your app: "LLM serving is extreme
  I/O-bound, so async."
- *"What breaks if you call a sync HTTP client in an async route?"* — The event loop blocks;
  *all* concurrent requests stall, not just this one. Fix: async client or `to_thread`.
- *"How does your streaming work end to end?"* — Ollama streams chunks → async generator
  yields SSE lines → StreamingResponse → client renders progressively; final event carries the
  validated JSON.
- *"At scale?"* — Multiple Uvicorn workers per pod, HPA across pods (Chapter 7), the semaphore
  becomes a proper queue, and the state (SQLite) externalizes to Postgres — SQLite is
  single-writer and node-local, which is exactly why it's the honest choice locally and the
  first thing to swap at scale.

---

## Chapter 6 — Docker

### The mental model

A container is **a process with blinders on**, not a VM. Same kernel as the host, but
namespaces make it see its own filesystem/network/process tree, and cgroups cap its CPU/RAM.
An **image** is the frozen filesystem + metadata the process starts from; a container is a
running instance of an image. Images are built in **layers** — each Dockerfile instruction
adds one, layers are cached and shared — which is why instruction *order* matters.

### Why it exists

"Works on my machine" — environments drifted between dev, CI, and prod. VMs solved isolation
but cost a full OS each. Containers give near-native performance with reproducible,
shippable environments: the image *is* the environment.

### Core concepts

**Layer caching.** Docker rebuilds only from the first changed instruction downward. So: copy
dependency manifests and install deps *first*, copy your source *last* — then editing code
reuses the cached (slow) dependency layer. With uv:

```dockerfile
FROM python:3.11-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project   # cached unless deps change
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.11-slim
RUN useradd -m app
WORKDIR /app
COPY --from=builder /app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Multi-stage builds** (the two `FROM`s above): build tools live in the builder stage; the
runtime image carries only the venv and code — smaller, fewer CVEs. **Non-root user**: if the
process is compromised, the blast radius inside the container is a normal user, not root.
Interviewers read a Dockerfile the way they read code — multi-stage + non-root + pinned
versions is the "this person has shipped" signature.

**Networking mental model.** Each container gets its own network namespace. In Compose,
services reach each other by service name (`http://jaeger:4317`) on a shared bridge network.
The host is *not* `localhost` from inside a container — it's `host.docker.internal` (Mac/Win)
— which is precisely how your containerized API reaches Ollama on the host.

**Compose** is declarative multi-container dev: one `compose.yaml` describing services,
networks, volumes, env. It's dev/CI tooling — Kubernetes is its production counterpart, not
its competitor.

### In this project

- `day3-service/Dockerfile` — the multi-stage file above.
- `compose.yaml` — `api` + `jaeger`, with `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- CI builds the image; `kind load docker-image devops-copilot:sha` puts it in the cluster
  without a registry (know that this replaces a push to ACR in the cloud path).

### Interview drill

- *"Container vs VM?"* — Shared kernel + namespaces/cgroups vs full guest OS; startup ms vs
  minutes; weaker isolation boundary (mention it — knowing containers are *not* a security
  boundary like VMs is senior).
- *"Why is your Dockerfile ordered that way?"* — Layer cache: deps before code.
- *"Why multi-stage / non-root?"* — Image size + attack surface; least privilege.
- *"At scale?"* — Image scanning (Trivy) in CI, image signing, distroless/slim bases, a real
  registry (ACR) with retention policies, and reproducible builds via lockfiles (`uv.lock`).

---

## Chapter 7 — Kubernetes

### The mental model

Kubernetes is a **control loop over desired state**. You submit YAML describing what should
exist ("3 replicas of this image, this much memory, this port"); controllers perpetually
compare *desired* vs *actual* and act to converge them. You never tell K8s *how* — you declare
*what*, and reconciliation does the rest. Pod dies → the Deployment controller notices actual
(2) < desired (3) → starts one. That single idea explains almost everything else.

(Notice the family resemblance: `kubectl apply` is idempotent declarative convergence, exactly
like Terraform and exactly like your ingestion pipeline. "Declare state, reconcile, re-run
safely" is arguably *the* DevOps idea, and you now have three implementations of it in one
repo. Use that line.)

### Why it exists

Docker runs containers on one machine. Production needs: many machines, scheduling (which node
has room?), self-healing, rolling updates without downtime, service discovery, config/secret
distribution, autoscaling. Kubernetes is the standard answer.

### Core concepts

- **Pod** — the atom: one or more containers sharing network/storage. You almost never create
  pods directly.
- **Deployment** — desired state for stateless pods: replica count, image, update strategy.
  Rolling updates (new ReplicaSet up, old one down, gradually) and `kubectl rollout undo` for
  rollback.
- **Service** — a stable virtual IP + DNS name in front of ephemeral pods (pods die and
  change IPs; Services don't). ClusterIP (internal), NodePort, LoadBalancer (cloud).
- **ConfigMap / Secret** — config and sensitive config, injected as env vars or files.
  (Secrets are base64, *not* encrypted at rest by default — knowing that is a classic
  interview checkpoint; the real answers are encryption-at-rest config, external secret
  stores like Azure Key Vault + CSI driver.)
- **Probes** — liveness ("restart me if this fails") vs readiness ("don't send me traffic
  yet"). Your `/healthz` backs both; readiness should verify Ollama/MCP reachability.
- **Resources** — `requests` (scheduling reservation) vs `limits` (hard cap; exceed memory →
  **OOMKilled**, which is literally one of your Day 5 synthetic incidents).
- **HPA** — Horizontal Pod Autoscaler: scale replicas on CPU/memory/custom metrics. Custom
  metrics (queue depth, p95 latency) is the right answer for LLM workloads, since CPU is a
  poor proxy when the bottleneck is a downstream model.
- **Namespaces** — virtual clusters for isolation/quotas.
- **kind** — Kubernetes-in-Docker: a real API server for local dev; what your pipeline
  deploys to.

### In this project

- `k8s/deployment.yaml` (probes, requests/limits, image from CI, env from
  ConfigMap/Secret), `service.yaml`, `hpa.yaml`.
- The CD stage runs `kubectl apply -k` + `kubectl rollout status` — a *gate*: the pipeline
  fails if the rollout doesn't converge.
- Day 5: the agent reads this cluster (deployments, pod logs, events) and diagnoses the
  broken deployments you plant.

### Interview drill

- *"Walk me through what happens on `kubectl apply` of a Deployment."* — API server persists
  desired state → Deployment controller creates/updates a ReplicaSet → scheduler binds pods to
  nodes → kubelet pulls images and starts containers → readiness gates Service traffic.
  Narrating that chain fluently is the single highest-value K8s interview asset.
- *"Liveness vs readiness?"* — Restart vs traffic; wrong liveness checks cause restart storms
  (e.g. liveness probing a dependency: dependency blips → whole fleet restarts).
- *"Requests vs limits? What's OOMKilled?"* — Scheduling vs cap; and you can point at your own
  incident demo.
- *"At scale?"* — Multi-node (AKS — which your Terraform already defines), pod disruption
  budgets, HPA on custom metrics, GitOps (Argo CD: the cluster pulls desired state from git —
  the same reconciliation idea again, one level up).

---

## Chapter 8 — CI/CD with Azure DevOps

### The mental model

A pipeline is **your deployment process written as code and run by a robot on every change**.
CI (continuous integration): every commit is built and tested immediately, so integration
pain is paid in small installments. CD (continuous delivery/deployment): the artifact that
passed CI flows through environments to production via automated, gated promotion. The prize
is not speed per se — it's that releases become boring, reversible, and frequent.

Azure DevOps is Microsoft's suite around that: **Repos** (git hosting + PR policies),
**Pipelines** (CI/CD), **Boards** (work tracking), **Artifacts** (package feeds), Test Plans.

### Why it exists

Manual deployment = snowflake releases, "deployment days", human error, and unmergeable
long-lived branches. Pipelines-as-code (the `azure-pipelines.yml` living *in the repo*) means
the process is versioned, reviewed, and reproducible like any other code.

### Core concepts

**YAML anatomy — the hierarchy is the whole grammar:**

```
Pipeline
└─ Stages     (major phases: CI, CD, Eval — run on agents, can gate on approvals)
   └─ Jobs    (units that run on ONE agent; jobs in a stage can run in parallel)
      └─ Steps (script | task — sequential within a job)
```

```yaml
trigger:
  branches: { include: [main] }

pool: { name: SelfHosted }        # your laptop's agent pool

stages:
- stage: CI
  jobs:
  - job: test
    steps:
    - script: uv sync --frozen && uv run ruff check . && uv run pytest -q
      displayName: Lint & test
  - job: build
    dependsOn: test
    steps:
    - script: docker build -t devops-copilot:$(Build.SourceVersion) day3-service/
      displayName: Build image
    - publish: day3-service/k8s
      artifact: manifests

- stage: CD
  dependsOn: CI
  jobs:
  - deployment: deploy_kind
    environment: local-kind        # environment = approval/check attachment point
    strategy:
      runOnce:
        deploy:
          steps:
          - download: current
            artifact: manifests
          - script: |
              kind load docker-image devops-copilot:$(Build.SourceVersion)
              kubectl apply -k $(Pipeline.Workspace)/manifests
              kubectl rollout status deploy/devops-copilot --timeout=120s
```

Vocabulary to own: **trigger** (what starts it: branch push, PR, schedule), **pool/agent**
(the machine that executes jobs — Microsoft-hosted VMs or **self-hosted**, i.e. a daemon you
register on your own machine), **task** (a packaged reusable step, e.g. `Docker@2`),
**variables & variable groups** (config, secret-able, linkable to Azure Key Vault), **service
connection** (stored credentials to external systems — Azure subscription, registry — so
secrets never live in YAML), **environment** (a named deployment target you attach approvals
and checks to), **artifacts** (files published by one stage, consumed by another — the
mechanism that guarantees you deploy *the exact thing you tested*), **templates** (reusable
YAML — the DRY mechanism across pipelines).

**Self-hosted agents** matter twice for you: they're free (one free self-hosted parallel job),
and they run *on your machine*, which is the only way a cloud pipeline can deploy to a kind
cluster living on your laptop. In companies, self-hosted agents exist for private-network
access, custom hardware, and cost — same reasoning, bigger scale.

**Boards & Repos in one honest paragraph.** Boards: work items (Epic → Feature → User Story →
Task/Bug) on boards/sprints; commits and PRs link with `AB#123`, so merged code closes work
items — full traceability from requirement to deploy. Repos: git with branch policies —
require PR + N reviewers + a passing *build validation pipeline* before merge to main. Set
both up for real on this project (a small sprint for Days 4–5, branch policy on main); it
takes minutes and converts a resume claim into a demo.

**Rollback strategy.** Something a senior is always asked: your options are re-deploy the
previous image tag (cheap, your default — this is why images are tagged with the commit SHA,
never `latest`), `kubectl rollout undo` (fast but drifts from git), or roll *forward* with a
fix. Deployment strategies that reduce the need: rolling (default), blue-green (two full
environments, flip traffic), canary (small % first, watch metrics, then ramp).

### In this project

- `day4-devops/azure-pipelines.yml`: CI (ruff, pytest, docker build) → CD (kind deploy with
  environment approval) → **Eval** (run `eval.py` against the deployed service, publish the
  scorecard as an artifact, fail under threshold). Quality gates on *AI behavior*, not just on
  unit tests — that stage is the sentence you say in both interviews.
- One helper script in PowerShell and one in Bash under `scripts/` — the JD lists both;
  make the claim checkable.
- Boards sprint + branch policy on main, wired to the CI pipeline as build validation.

### Interview drill

- *"Stages vs jobs vs steps?"* — Hierarchy above; jobs are the agent-assignment unit and the
  parallelism unit; stages are the gating/approval unit.
- *"How do secrets get into a pipeline safely?"* — Service connections for cloud creds;
  secret variables / variable groups, ideally backed by Key Vault; never plaintext YAML, and
  secrets are masked in logs.
- *"Microsoft-hosted vs self-hosted agents?"* — Managed clean VMs per run vs your
  machines: network access (private clusters!), caching, custom deps, cost. Yours is
  self-hosted *because* the deploy target is local — say the real reason.
- *"How do you guarantee you deploy what you tested?"* — Build once, publish immutable
  artifacts (image tagged by SHA), every later stage consumes the artifact; never rebuild
  per environment.
- *"At scale?"* — Templates shared across repos, deployment rings, canary + automated
  rollback on metric regression (which needs Chapter 9's observability — the loop closes).

---

## Chapter 9 — Infrastructure as Code: Terraform and Bicep

### The mental model

The same idea as Kubernetes, one level up: **declare the infrastructure you want; a tool
diffs desired vs actual and converges them**. `terraform plan` shows the diff, `terraform
apply` executes it. Infrastructure stops being remembered click-history in a portal and
becomes reviewed, versioned, reproducible code.

### Why it exists

ClickOps doesn't scale, can't be reviewed, can't be reproduced ("who changed the firewall?"),
and drifts. IaC gives you PRs on infrastructure, environments stamped from the same code
(dev/stage/prod as parameterized instances), and disaster recovery as `apply` on a fresh
subscription.

### Core concepts

**Terraform.** HCL language, **providers** (plugins that translate resources to cloud APIs —
`azurerm` for Azure), and the crucial piece: **state**. Terraform keeps a file mapping your
code to real resource IDs; the plan is a three-way diff of code ⇄ state ⇄ reality. State is
why teams need a **remote backend** (Azure Storage blob) with **locking** — two engineers
applying concurrently against local state files is how infrastructure gets destroyed.
Workflow: `init` (fetch providers/backend) → `validate` → `plan` (review the diff — in CI,
a human approves the plan) → `apply`. Modules = reusable parameterized units.

```hcl
resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-devops-copilot"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  default_node_pool {
    name       = "default"
    node_count = 2
    vm_size    = "Standard_B2s"
  }
  identity { type = "SystemAssigned" }
}
```

**Bicep.** Azure's native IaC DSL, compiled to ARM templates (the JSON that Azure Resource
Manager actually consumes — nobody enjoys writing raw ARM; Bicep exists to fix its
ergonomics). Key contrast with Terraform: **no state file** — ARM deployments are themselves
the desired-state engine and Azure knows what exists; deployments are incremental by default.
Azure-only, day-zero support for new Azure features, first-class in Azure Pipelines
(`AzureResourceManagerTemplateDeployment` task).

**How to answer "Terraform vs Bicep vs ARM":** ARM is the compilation target, not something
you author. Bicep when you're all-in on Azure and want no state management and instant feature
coverage. Terraform when you're multi-cloud or multi-provider (it also manages Datadog,
GitHub, Kubernetes, Cloudflare...), want one language everywhere, and accept state as the tax.
You have real experience with both — this project's `infra/` proves it with the same stack
expressed twice.

**Idempotency & drift.** Running apply twice changes nothing (there's the theme again). Drift
= someone changed reality outside the code; `plan` surfaces it; the mature stance is "the
portal is read-only, changes go through PRs."

### In this project

- `infra/terraform/`: resource group, ACR, AKS, Log Analytics; variables for
  size/location; remote-backend stanza written but commented (local state for the demo);
  validated with `init/validate/plan` on a free subscription — you can show a real plan
  output without spending a cent.
- `infra/bicep/`: the same resources in Bicep; `az bicep build` compiles it, proving
  correctness offline.
- The README's scaling note: swap kind for this AKS by changing the pipeline's service
  connection + kube context — the manifests and pipeline stages are unchanged. That's the
  payoff line for designing local-first but production-shaped.

### Interview drill

- *"What is Terraform state and why remote?"* — Mapping code⇄reality enabling the diff;
  remote + locked for teams; state can contain secrets → treat as sensitive.
- *"What happens if two people apply at once?"* — State locking prevents it; without it,
  corruption/races. (This is a favorite.)
- *"Plan vs apply in CI?"* — plan on PR (posted for review), apply on merge with approval;
  never blind-apply.
- *"At scale?"* — Modules + registries, per-env state separation, policy as code
  (Azure Policy / OPA / Sentinel) gating plans, and drift detection on schedule.

---

## Chapter 10 — Observability: OpenTelemetry, Prometheus, Grafana (and the Azure mapping)

### The mental model

Monitoring answers *"is it broken?"*; observability answers *"why?"* — the ability to
interrogate a system's internal state from its outputs, including for failures you never
predicted. Three signal types (the "pillars"), each answering a different question:

- **Metrics** — cheap aggregated numbers over time. *What is happening?* (rate, errors,
  latency)
- **Traces** — the tree of timed spans one request produced across components. *Where did
  this request spend its time / fail?*
- **Logs** — timestamped events with detail. *What exactly happened at that moment?*

The senior move is correlating them: a latency spike on the dashboard (metric) → exemplar
trace → the slow span → its logs. Your stack wires exactly that path.

### Why it exists

In a monolith you attached a debugger. In a distributed system a request crosses processes
(API → agent → LLM → MCP → kubectl), and no single log file tells the story. Tracing was the
answer (Google's Dapper → Jaeger/Zipkin → OpenTelemetry as the vendor-neutral standard).

### Core concepts

**OpenTelemetry (OTel)** is the standard for *producing* signals: APIs/SDKs to create spans
and metrics, **context propagation** (trace IDs travel across process boundaries via HTTP
headers, so spans from different services join into one trace), and **OTLP**, the wire
protocol exporters speak. Grasp the separation: OTel *generates and ships* telemetry; Jaeger /
Prometheus / Langfuse / App Insights *store and visualize* it. Instrument once with OTel and
the backend is swappable — the same "standard plug" argument as MCP and the OpenAI API shape.
You now hold three instances of the pattern; interviewers notice people who see patterns.

A **span** = named, timed operation + attributes + parent. A **trace** = the span tree for one
request. For LLM systems, spans carry the interesting attributes: model, token counts,
tool name, whether output validated — that's what makes agent debugging possible (Chapter 4's
"I debug agents with traces").

**Prometheus** is *pull-based* metrics: your app exposes current values as text at `/metrics`;
Prometheus scrapes every N seconds into a time-series DB queried with **PromQL**. Pull (vs
push) means Prometheus discovers targets (via ServiceMonitors in K8s) and an app being
un-scrapeable is itself a signal (`up == 0`). Metric types you'll actually use: **Counter**
(only goes up: requests_total, tokens_total), **Gauge** (goes both ways: in-flight requests),
**Histogram** (distribution in buckets: request duration — this is where p50/p95 come from).

Why percentiles, never averages: latency is skewed; the mean hides the pain. p50 = typical,
p95/p99 = the experience of your unluckiest users, which is what SLOs are written against.
PromQL you should be able to read aloud:
`histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))`.

**Grafana** is the visualization layer over Prometheus (and other sources): dashboards as
JSON — which means dashboards live *in the repo* and are code-reviewed like everything else.

**The Azure mapping (for the JD):** Azure Monitor is the platform umbrella; **Application
Insights** ≈ traces + app telemetry (APM); **Log Analytics** ≈ log store queried with **KQL**
(their PromQL-for-logs); Managed Prometheus/Grafana exist as services. Because you
instrumented with OTel, pointing your exporter at App Insights
(`azure-monitor-opentelemetry`) instead of Jaeger is a one-line change — that sentence is
your bridge from the local demo to their Azure reality.

### In this project

- `telemetry.py`: OTel tracer; spans for request → agent iteration → each LLM call (attrs:
  model, tokens) → each MCP tool call (attrs: tool, duration); OTLP exporter → Jaeger
  all-in-one.
- `prometheus_client` metrics: `triage_requests_total`, `triage_duration_seconds`
  (histogram), `llm_tokens_total`, `triage_errors_total`.
- kube-prometheus-stack in kind; ServiceMonitor scrapes the API; `grafana-dashboard.json`
  shows rate/errors/p50/p95/tokens — committed to the repo.
- Demo beat: one `/triage` request shown as a single Jaeger trace, nested to the level of
  individual tool calls.

### Interview drill

- *"Metrics vs logs vs traces?"* — What / why-where / exactly-what; plus cost profile
  (metrics cheapest, logs most expensive at volume).
- *"Push vs pull monitoring?"* — Prometheus pulls: discovery + up-detection; push gateways
  exist for batch jobs.
- *"Why percentiles?"* — Skewed distributions; SLOs target tails.
- *"How would you monitor an LLM app specifically?"* — Everything above *plus* token
  cost/rates, per-model latency, tool-call failure rates, structured-output validation
  failures, and quality metrics from evals trended over time (Chapter 11) — quality is a
  production metric, not a research afterthought.
- *"At scale?"* — Sampling traces (head vs tail sampling), metric cardinality discipline
  (no user IDs in labels!), SLOs + error budgets driving alerts — alert on symptoms (p95,
  error rate), not causes (CPU).

---

## Chapter 11 — Evaluating AI Systems (LLM-as-Judge)

### The mental model

Evals are **unit tests for behavior you can't assert with `==`**. A traditional test checks
exact outputs; an LLM's output varies in wording while being right or wrong in *substance*.
So you build a labeled dataset, define what "good" means as a rubric, and score the system
against it — turning "the agent seems better now" into "groundedness went from 0.71 to 0.84,
p95 latency +300 ms". That number is what the AI JD means by *measurable AI outcomes*, and
"eval score as a CI quality gate" is what turns it into a DevOps sentence.

### Why it exists

Without evals, every change (prompt tweak, model swap, chunk-size change) is vibes-based, and
regressions ship silently. Evals are to LLM systems what regression suites are to code: the
thing that makes iteration *safe*. They're also how you compare models honestly — e.g.
whether qwen2.5:7b is actually good enough vs a hosted model *for your task*.

### Core concepts

**The eval dataset.** 10–20 real-shaped tickets, each labeled with expected category and notes
on what a correct answer must contain (which runbook applies, key steps). Small is fine;
*representative and honest* beats large. Include hard cases: ambiguous tickets, ones where
the KB has no answer (the correct behavior is saying so — punish confident fabrication).

**Three scoring tiers, cheapest first:**
1. **Deterministic checks** — code, no LLM: did the output validate against `TriageResult`?
   Is the category one of the allowed values? Do all cited article ids actually exist, and
   were they actually retrieved? (That last check is a *groundedness* proxy that costs
   nothing.) Latency and token counts are recorded here too.
2. **Exact-match-ish** — category accuracy vs labels: a plain percentage.
3. **LLM-as-judge** — a model grades what code can't: is the reply *actually supported* by
   the cited articles (groundedness)? Is it correct per the label notes? Helpful in tone and
   actionability? Used because human review doesn't scale and string metrics (BLEU-style
   overlap) don't measure meaning.

**Judge design — where all the pitfalls live:**
- **Rubric anchoring**: never ask "rate 1–10" (uncalibrated, drifts). Define each score:
  "groundedness 1 = every claim traceable to a cited chunk; 0.5 = minor unsupported details;
  0 = contains claims contradicting or absent from citations." Few-shot the rubric with a
  good and a bad example.
- **Give the judge the evidence**: the ticket, the answer, *and the cited chunks* — judging
  groundedness without the sources is meaningless.
- **Known biases**: self-preference (models favor their own outputs — so judge with a
  *different/larger* model than the agent, e.g. a bigger Ollama model or Gemini's free tier:
  "never let a model grade its own homework"); position bias in pairwise comparisons (swap
  the order and average); verbosity bias (longer ≠ better — say so in the rubric).
- **Validate the judge once**: hand-score ~10 outputs yourself, correlate with the judge. If
  it disagrees with you constantly, fix the rubric before trusting the numbers.

**The scorecard** is the deliverable: category accuracy %, mean groundedness / correctness /
helpfulness, structured-output validity rate, latency p50/p95, tokens per ticket. Persist per
run (SQLite — you already store runs), trend it in Grafana, gate CI on it.

### In this project

- `eval/dataset.jsonl` — labeled tickets, including no-answer-exists traps.
- `eval/judge.py` — rubric-anchored judge with evidence, distinct judge model.
- `eval/eval.py` — runs the dataset through the *deployed* `/triage` endpoint (evaluating
  the whole system, not a lab replica), prints the scorecard, exits non-zero under
  thresholds → the pipeline's Eval stage.

### Interview drill

- *"How do you measure AI outcomes?"* — Labeled set + tiered scoring (deterministic →
  accuracy → rubric-anchored judge) + operational metrics, trended over time, gating CI.
- *"Problems with LLM-as-judge?"* — Self-preference, position, verbosity biases; uncalibrated
  scales; fixes: distinct judge, rubrics + few-shots, order-swapping, human spot-validation.
- *"What did the eval change?"* — Have one true story ready: e.g. "the eval caught that
  reducing chunk overlap improved latency but dropped groundedness 10 points, so I reverted."
  A concrete regression-caught story is worth more than any framework name.
- *"At scale?"* — Bigger datasets sampled from production traces, online evals on live
  traffic samples, A/B testing prompts/models, human review queues for low-judge-confidence
  cases.

---

## Chapter 12 — How It All Hangs Together (read before the interview)

One paragraph you should be able to deliver cold:

> "I built a support-triage agent for DevOps incidents. Unstructured runbooks go through an
> idempotent pipeline — chunk on structure, embed locally with nomic-embed-text, index in
> sqlite-vec. An MCP server exposes search and cluster-inspection tools; the agent — a
> bounded tool-calling loop, hand-rolled and then reproduced in ADK over a local Ollama
> model — triages tickets into a validated structured result with citations, and can diagnose
> a live Kubernetes incident from pod logs against the runbooks. It's wrapped in an async
> FastAPI service that streams over SSE, traced end-to-end with OpenTelemetry into Jaeger,
> with Prometheus metrics on a Grafana dashboard. Azure DevOps Pipelines builds, tests, and
> deploys it to Kubernetes on a self-hosted agent, publishes an LLM-as-judge scorecard as a
> build artifact, and fails the build if quality regresses. Infra for the cloud version is
> written twice — Terraform and Bicep — and validated with plan. Everything runs on my
> laptop; every piece is the local twin of a production component, and I can tell you the
> swap for each."

**The recurring ideas (interviewers reward people who see them):**

1. **Declare desired state, reconcile idempotently** — the ingestion pipeline, `kubectl
   apply`, Terraform. One idea, three implementations, one repo.
2. **Standard interfaces decouple producers from consumers** — MCP (tools), the OpenAI API
   shape (models), OpenTelemetry (telemetry), ASGI (servers). Swap any side without touching
   the other.
3. **Immutable artifacts + gates** — build once, tag by SHA, promote the same artifact
   through test → deploy → eval; gate every promotion (tests, rollout status, judge score).
4. **Bounded autonomy** — the agent chooses *within* limits: iteration caps, timeouts,
   read-only defaults, confirmation-gated writes, human approvals on environments. Same
   philosophy as change management, applied to a model.
5. **If you can't see it, you can't run it** — traces for debugging, metrics for operating,
   evals for quality. All three trended, all three in the repo.

**Final drill — for every component, answer aloud:**
*why this / what's the tradeoff / what changes at scale?*
If any answer takes you longer than 30 seconds, reread that chapter, then rebuild that piece
from scratch without looking. Building it twice is the fastest way to own it.
