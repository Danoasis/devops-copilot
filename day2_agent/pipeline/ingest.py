"""Idempotent ingestion: load -> clean -> chunk -> embed -> upsert.

Content-hash per document; unchanged docs are skipped, so re-running on an
unchanged corpus embeds nothing (the property you also demand of `terraform
apply` and `kubectl apply` — declare state, reconcile, re-run safely).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from day2_agent.pipeline.chunker import chunk_document
from day2_agent.pipeline.index import VectorIndex


@dataclass
class IngestReport:
    ingested: int = 0
    skipped: int = 0
    removed: int = 0
    chunks_written: int = 0

    def __str__(self) -> str:
        return (
            f"ingested={self.ingested} skipped={self.skipped} "
            f"removed={self.removed} chunks_written={self.chunks_written}"
        )


def _clean(markdown: str) -> str:
    """Light normalization: collapse >2 blank lines, strip trailing whitespace."""
    text = re.sub(r"\n{3,}", "\n\n", markdown)
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def run_ingest(kb_dir: Path, index: VectorIndex, *, rebuild: bool = False) -> IngestReport:
    report = IngestReport()
    files = sorted(kb_dir.glob("*.md"))
    seen: set[str] = set()

    for path in files:
        doc_id = path.stem.split("-")[0] + "-" + path.stem.split("-")[1] \
            if re.match(r"^KB-\d+", path.stem) else path.stem
        seen.add(doc_id)
        raw = path.read_text(encoding="utf-8")
        cleaned = _clean(raw)
        content_hash = hashlib.sha256(cleaned.encode()).hexdigest()

        if not rebuild and index.doc_hash(doc_id) == content_hash:
            report.skipped += 1
            continue

        chunks = chunk_document(doc_id, cleaned)
        n = index.upsert_document(
            doc_id, str(path), _title_of(cleaned, path.stem), content_hash, chunks
        )
        report.ingested += 1
        report.chunks_written += n

    # Remove documents whose source file disappeared (true reconciliation).
    for (doc_id,) in index.db.execute("SELECT doc_id FROM documents").fetchall():
        if doc_id not in seen:
            index.delete_document(doc_id)
            report.removed += 1
    return report
