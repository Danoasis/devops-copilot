"""Structure-first markdown chunking.

Strategy (see FUNDAMENTALS ch.3): split on markdown headers first, because runbook
sections are semantically self-contained; then pack/split long sections to a target
size with a small overlap so boundary sentences aren't orphaned. Every chunk keeps
its heading path so it can be understood (and embedded) out of context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

HEADER_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    heading: str  # "Doc Title > Section" breadcrumb
    text: str

    @property
    def embed_text(self) -> str:
        """What actually gets embedded: breadcrumb + body, so 'Resolution' chunks
        still carry which runbook they belong to."""
        return f"{self.heading}\n\n{self.text}"


def _split_sections(markdown: str) -> list[tuple[str, str]]:
    """Split a markdown doc into (heading_path, body) sections."""
    title = ""
    stack: list[tuple[int, str]] = []  # (level, heading)
    sections: list[tuple[str, list[str]]] = []
    current: list[str] = []

    def flush() -> None:
        if current and any(line.strip() for line in current):
            path = " > ".join([title] + [h for _, h in stack]) if title else " > ".join(
                h for _, h in stack
            )
            sections.append((path or title or "(document)", current.copy()))
        current.clear()

    for line in markdown.splitlines():
        m = HEADER_RE.match(line)
        if m:
            flush()
            level, heading = len(m.group(1)), m.group(2).strip()
            if level == 1 and not title:
                title = heading
                stack = []
                continue
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading))
        else:
            current.append(line)
    flush()
    return [(path, "\n".join(lines).strip()) for path, lines in sections]


def _pack_paragraphs(body: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Pack paragraphs up to max_chars; start each new pack with the previous tail
    (overlap). Hard-split any single paragraph longer than max_chars."""
    paras: list[str] = []
    for p in re.split(r"\n\s*\n", body):
        p = p.strip()
        if not p:
            continue
        while len(p) > max_chars:  # pathological single paragraph
            paras.append(p[:max_chars])
            p = p[max_chars - overlap_chars:]
        paras.append(p)

    packs: list[list[str]] = []
    cur: list[str] = []
    size = 0
    for p in paras:
        if cur and size + len(p) + 2 > max_chars:
            packs.append(cur)
            tail = cur[-1]
            cur = [tail, p] if len(tail) <= overlap_chars else [p]
            size = sum(len(x) + 2 for x in cur)
        else:
            cur.append(p)
            size += len(p) + 2
    if cur:
        packs.append(cur)
    return ["\n\n".join(pack) for pack in packs]


def chunk_document(
    doc_id: str, markdown: str, *, max_chars: int = 1600, overlap_chars: int = 200
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in _split_sections(markdown):
        for text in _pack_paragraphs(body, max_chars, overlap_chars):
            chunks.append(Chunk(doc_id=doc_id, heading=heading, text=text))
    return chunks
