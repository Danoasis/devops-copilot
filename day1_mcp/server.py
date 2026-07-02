"""MCP server exposing the DevOps knowledge base (Day 1) and, when explicitly
enabled, cluster ops tools (Day 5).

Tools return JSON strings: maximally portable across MCP client versions, and the
model reads JSON fine. Docstrings below are not decoration — FastMCP turns them
into the tool descriptions the model sees, so they are prompt engineering
(FUNDAMENTALS ch.2).

Run standalone:            python day1_mcp/server.py           (stdio transport)
Inspect interactively:     npx @modelcontextprotocol/inspector python day1_mcp/server.py
Enable Day 5 ops tools:    COPILOT_ENABLE_OPS_TOOLS=1 python day1_mcp/server.py
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from common.config import settings

mcp = FastMCP("devops-copilot-kb")

# ---------------------------------------------------------------------------
# Semantic search with graceful degradation:
#   index exists + Ollama reachable  -> semantic (Day 2 behavior)
#   otherwise                        -> keyword fallback (Day 1 behavior)
# Same MCP contract either way — that decoupling is the point of the protocol.
# ---------------------------------------------------------------------------
_index = None
_index_error: str | None = None


def _pinned_embed_model(db_path) -> tuple[str | None, int | None]:
    """Read the (embed_model, dim) pin the index stored at build time."""
    import sqlite3
    try:
        db = sqlite3.connect(db_path)
        rows = dict(db.execute("SELECT key, value FROM meta").fetchall())
        db.close()
        dim = rows.get("embed_dim")
        return rows.get("embed_model"), int(dim) if dim else None
    except Exception:
        return None, None


def _get_index():
    global _index, _index_error
    if _index is None and _index_error is None:
        try:
            from day2_agent.pipeline.embedding import FakeEmbedder, OllamaEmbedder
            from day2_agent.pipeline.index import VectorIndex

            if not settings.db_path.exists():
                raise FileNotFoundError(
                    f"no index at {settings.db_path} (run: copilot-ingest)"
                )
            # Honor the pin: an index built with `copilot-ingest --fake` must be
            # queried with the same fake embedder (vectors live in that space).
            # This also makes the full semantic path testable with no Ollama.
            model, dim = _pinned_embed_model(settings.db_path)
            if model and model.startswith("fake/"):
                embedder = FakeEmbedder(dim=dim or 64)
            else:
                embedder = OllamaEmbedder()
            _index = VectorIndex(settings.db_path, embedder)
        except Exception as exc:  # degrade, don't die
            _index_error = str(exc)
    return _index


def _keyword_search(query: str, k: int) -> list[dict]:
    terms = [t for t in query.lower().split() if len(t) > 2]
    hits: list[dict] = []
    for path in sorted(settings.kb_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        score = sum(lower.count(t) for t in terms)
        if score > 0:
            first = next((ln for ln in text.splitlines() if ln.startswith("# ")), path.stem)
            hits.append({
                "doc_id": "-".join(path.stem.split("-")[:2]),
                "heading": first.lstrip("# ").strip(),
                "snippet": text[:400],
                "score": score,
            })
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:k]


@mcp.tool()
def search_kb(query: str, k: int = 5) -> str:
    """Search the DevOps knowledge base of runbooks for a query.

    Use short, symptom-focused queries (e.g. 'pod CrashLoopBackOff no logs',
    'terraform state lock', 'pipeline agent offline'). Returns a JSON list of
    hits: {doc_id, heading, text/snippet, score}. Cite doc_id values in answers.
    """
    index = _get_index()
    if index is not None:
        try:
            hits = index.search(query, k=k)
            return json.dumps({
                "mode": "semantic",
                "hits": [
                    {"doc_id": h.doc_id, "heading": h.heading,
                     "text": h.text, "score": h.score}
                    for h in hits
                ],
            })
        except Exception as exc:
            return json.dumps({"mode": "error", "error": str(exc),
                               "hits": _keyword_search(query, k)})
    return json.dumps({
        "mode": "keyword_fallback",
        "note": _index_error,
        "hits": _keyword_search(query, k),
    })


@mcp.tool()
def get_article(article_id: str) -> str:
    """Fetch the full markdown text of one runbook by id (e.g. 'KB-003').

    Use after search_kb when a hit looks relevant but you need the complete
    Diagnosis/Resolution steps. Returns the raw markdown, or an error JSON if
    the id does not exist.
    """
    matches = list(settings.kb_dir.glob(f"{article_id}-*.md")) or \
        list(settings.kb_dir.glob(f"{article_id}.md"))
    if not matches:
        known = sorted("-".join(p.stem.split("-")[:2]) for p in settings.kb_dir.glob("KB-*.md"))
        return json.dumps({"error": f"unknown article_id '{article_id}'", "known_ids": known})
    return matches[0].read_text(encoding="utf-8")


@mcp.tool()
def list_tickets(status: str = "open") -> str:
    """List sample support tickets by status ('open', 'closed', or 'all').

    Returns a JSON list of {id, status, priority, subject, body}.
    """
    tickets = json.loads((settings.kb_dir / "tickets.json").read_text(encoding="utf-8"))
    if status != "all":
        tickets = [t for t in tickets if t.get("status") == status]
    return json.dumps(tickets)


@mcp.resource("kb://articles")
def kb_articles() -> str:
    """Catalog of all runbooks in the knowledge base (id + title)."""
    lines = ["# Knowledge base catalog", ""]
    for path in sorted(settings.kb_dir.glob("KB-*.md")):
        doc_id = "-".join(path.stem.split("-")[:2])
        title = next(
            (ln.lstrip("# ").strip() for ln in
             path.read_text(encoding="utf-8").splitlines() if ln.startswith("# ")),
            path.stem,
        )
        lines.append(f"- **{doc_id}** — {title}")
    return "\n".join(lines)


# --- Day 5: cluster ops tools, explicitly opt-in ---------------------------
if settings.enable_ops_tools:
    from day5_agentic_ops.ops_tools import register_ops_tools

    register_ops_tools(mcp)


if __name__ == "__main__":
    mcp.run()  # stdio transport
