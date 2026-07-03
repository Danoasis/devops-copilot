"""Platform architecture — the Python rendering of the diagram in
docs/PROJECT_PLAN.md.

Where the system diagram shows the *request path*, this one shows the
*platform view*: which Azure DevOps surfaces drive the build, what runs on
the laptop-as-self-hosted-agent, and where each backing service (Jaeger,
sqlite-vec, Ollama, kind + Prometheus/Grafana) sits.

Render:  python diagrams/platform_architecture.py
Outputs: docs/img/platform-architecture.{png,svg}
"""
from style import PALETTE, arrow, draw_box, draw_note, new_canvas, save

W, H = 14.0, 9.2
fig, ax = new_canvas(W, H, "DevOps Copilot — platform architecture",
                     "Azure DevOps drives it; a self-hosted agent (your laptop) runs all of it")

# ------------------------------------------------------------- azure -------
azdo = draw_box(
    ax, 3.9, 7.15, 6.2, 1.3, color=PALETTE["pipeline"],
    title="Azure DevOps",
    lines=["Repos  ·  Boards  ·  Pipelines  ·  Artifacts",
           "self-hosted agent = your laptop"])

# ------------------------------------------------------------- row 2 -------
client = draw_box(
    ax, 0.4, 4.7, 2.0, 1.5, color=PALETTE["neutral"],
    title="Client", lines=["curl / UI", "POST /triage"])

service = draw_box(
    ax, 3.3, 4.35, 4.1, 2.1, color=PALETTE["service"],
    title="FastAPI service",
    lines=["async · SSE streaming",
           "agent loop (day 2)",
           "Ollama via OpenAI-compat API"])

mcp = draw_box(
    ax, 9.0, 4.35, 3.3, 2.1, color=PALETTE["data"],
    title="MCP server",
    lines=["search_kb", "get_article · list_tickets",
           "get_pod_logs", "get_deploy_status"], mono_lines=True, line_size=8.8)

# ------------------------------------------------------------- row 3 -------
jaeger = draw_box(
    ax, 1.5, 1.3, 2.2, 1.3, color=PALETTE["obs"],
    title="Jaeger", lines=["trace UI", ":16686"])

sqlite = draw_box(
    ax, 4.6, 1.3, 2.7, 1.3, color=PALETTE["data"],
    title="SQLite + sqlite-vec", lines=["chunks · vectors · runs"])

ollama = draw_box(
    ax, 4.6, 0.0, 2.7, 0.95, color=PALETTE["model"],
    title="Ollama", lines=["chat + embed models"])

kind = draw_box(
    ax, 9.35, 0.75, 2.9, 1.85, color=PALETTE["ops"],
    title="kind cluster",
    lines=["devops-copilot deploy", "Prometheus", "Grafana"])

# ------------------------------------------------------------- arrows ------
arrow(ax, azdo.bottom, service.top, color=PALETTE["pipeline"],
      label="CI  lint · test · docker build\nCD  kubectl apply → kind",
      label_dx=1.85, label_dy=0.05, label_size=8.6)
arrow(ax, client.right, service.left, label="HTTP", color=PALETTE["neutral"],
      label_dy=0.18)
arrow(ax, service.right, mcp.left, label="stdio · tool calls",
      color=PALETTE["agent"], both=True, label_dy=0.18)
arrow(ax, service.bottom_at(0.18), jaeger.top, label="OTel traces",
      color=PALETTE["obs"], curve=0.12, label_dx=-0.55, label_dy=0.1)
arrow(ax, service.bottom_at(0.62), sqlite.top, label="embeddings · run log",
      color=PALETTE["data"], label_dx=1.0, label_dy=0.05)
arrow(ax, mcp.bottom, kind.top, label="kubectl", color=PALETTE["ops"],
      label_dx=0.55, label_dy=0.0)
arrow(ax, sqlite.bottom, ollama.top, color=PALETTE["model"], both=True, lw=1.2)

draw_note(ax, 5.95, -0.35,
          "one Ollama instance serves the chat model (triage) and the embedding model (index + queries)")
draw_note(ax, 12.35, 3.0, "deployed by the CD stage;\nscraped by Prometheus", ha="center")

for path in save(fig, "platform-architecture"):
    print("wrote", path)
