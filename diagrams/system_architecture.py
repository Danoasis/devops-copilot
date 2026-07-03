"""System architecture — the Python rendering of the diagram in README.md.

Flow it encodes (identical to the ASCII original):

    Azure DevOps pipeline (CI -> CD -> Eval) deploys
    ticket -> FastAPI service (day3) -> agent loop (day2) <-> Ollama
    FastAPI -> Prometheus/Grafana + OTel -> Jaeger
    agent loop <-> MCP client (stdio) -> MCP server (day1)
    MCP server -> search_kb -> sqlite-vec index <- ingest (nomic-embed-text)
    MCP server -> ops tools (day5): kubectl read-only, writes double-gated

Render:  python diagrams/system_architecture.py
Outputs: docs/img/system-architecture.{png,svg}
"""
from style import PALETTE, arrow, draw_box, draw_note, new_canvas, save

W, H = 14.0, 9.6
fig, ax = new_canvas(W, H, "DevOps Copilot — system architecture",
                     "agentic ticket triage: every box runs locally, zero cloud spend")

# ---------------------------------------------------------------- row 1 ----
pipeline = draw_box(
    ax, 4.1, 7.6, 5.8, 1.25, color=PALETTE["pipeline"],
    title="Azure DevOps Pipeline  (day 4)",
    lines=["CI  lint · test · build   →   CD  kind deploy   →   Eval  quality gate"])

# ---------------------------------------------------------------- row 2 ----
ticket = draw_box(ax, 0.35, 5.6, 1.5, 0.95, color=PALETTE["neutral"],
                  title="ticket", lines=["user / queue"])

service = draw_box(
    ax, 2.5, 5.25, 3.4, 1.65, color=PALETTE["service"],
    title="FastAPI service  (day 3)",
    lines=["POST /triage   SSE | JSON",
           "/healthz   /readyz   /metrics"], mono_lines=True)

agent = draw_box(
    ax, 6.9, 5.25, 3.1, 1.65, color=PALETTE["agent"],
    title="agent loop  (day 2)",
    lines=["bounded iterations · timeouts",
           "JSON repair · quality nudge",
           "OTel span per step"])

ollama = draw_box(
    ax, 11.0, 5.25, 2.6, 1.65, color=PALETTE["model"],
    title="Ollama",
    lines=["qwen2.5:7b  chat+tools", "nomic-embed-text", "local LLM · OpenAI API"])

# ---------------------------------------------------------------- row 3 ----
obs = draw_box(
    ax, 2.5, 2.4, 3.4, 1.7, color=PALETTE["obs"],
    title="Observability",
    lines=["Prometheus + Grafana", "rate · p50/p95 · tokens · errors",
           "OTel traces → Jaeger"])

mcp_client = draw_box(
    ax, 7.15, 3.15, 2.6, 0.95, color=PALETTE["agent"],
    title="MCP client", lines=["stdio transport"])

# ---------------------------------------------------------------- row 4 ----
server = draw_box(
    ax, 6.35, 0.45, 4.2, 1.95, color=PALETTE["data"],
    title="MCP server  (day 1)",
    lines=["search_kb", "get_article", "list_tickets"], mono_lines=True)

index = draw_box(
    ax, 11.35, 1.35, 2.3, 1.05, color=PALETTE["data"],
    title="sqlite-vec index", lines=["768-dim · cosine"])

ingest = draw_box(
    ax, 11.35, 0.1, 2.3, 0.9, color=PALETTE["data"],
    title="ingest", lines=["8 runbooks · idempotent"])

ops = draw_box(
    ax, 1.7, 0.45, 3.8, 1.4, color=PALETTE["ops"],
    title="ops tools  (day 5)",
    lines=["kubectl read-only by default",
           "writes double-gated: env + confirm"])

# --------------------------------------------------------------- arrows ----
arrow(ax, pipeline.bottom, service.top_at(0.75), label="deploys",
      color=PALETTE["pipeline"], curve=-0.12, label_dx=0.5)
arrow(ax, ticket.right, service.left, color=PALETTE["neutral"])
arrow(ax, service.right, agent.left, label="run agent",
      color=PALETTE["service"], label_dy=0.18)
arrow(ax, agent.right, ollama.left, label="chat / tool calls",
      color=PALETTE["model"], both=True, label_dy=0.18)
arrow(ax, service.bottom, obs.top, label="metrics + traces",
      color=PALETTE["obs"], label_dx=-1.05, label_dy=0.0)
arrow(ax, agent.bottom, mcp_client.top, label="tools",
      color=PALETTE["agent"], label_dx=0.55, label_dy=0.0)
arrow(ax, mcp_client.bottom, server.top, label="JSON-RPC",
      color=PALETTE["agent"], both=True, label_dx=0.72, label_dy=0.0)
arrow(ax, server.right, index.left, label="query",
      color=PALETTE["data"], label_dy=0.16)
arrow(ax, ingest.left, index.bottom_at(0.15), label="embed + upsert",
      color=PALETTE["data"], curve=0.25, label_dx=-1.3, label_dy=-0.28)
arrow(ax, server.left, ops.right, label="COPILOT_ENABLE_OPS_TOOLS=1",
      color=PALETTE["ops"], dashed=True, label_dy=0.20, label_size=8.0)

draw_note(ax, ollama.bottom[0], 4.95,
          "serves both chat and\nembedding models")
draw_note(ax, index.top[0], 2.72, "nomic-embed-text vectors")

for path in save(fig, "system-architecture"):
    print("wrote", path)
