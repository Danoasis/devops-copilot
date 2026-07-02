"""Chunker tests: the chunker is pure (no I/O, no LLM), so it gets the most
exact tests in the repo. If retrieval quality ever degrades, this is the
first layer to rule out."""
from day2_agent.pipeline.chunker import chunk_document

DOC = """# Payments runbook

Intro paragraph explaining scope.

## Symptoms

Pods restart continuously.

Exit code is 137.

## Fix

Raise the memory limit after profiling.
"""


def test_splits_on_headers():
    chunks = chunk_document("KB-XXX", DOC)
    headings = [c.heading for c in chunks]
    assert any("Symptoms" in h for h in headings)
    assert any("Fix" in h for h in headings)
    # every chunk carries its doc id for citation integrity downstream
    assert all(c.doc_id == "KB-XXX" for c in chunks)


def test_embed_text_includes_breadcrumb():
    """The heading breadcrumb is prepended so the vector encodes *where* the
    text lives, not just what it says — small trick, big retrieval win."""
    chunks = chunk_document("KB-XXX", DOC)
    sym = next(c for c in chunks if "Symptoms" in c.heading)
    assert sym.embed_text.startswith(sym.heading)
    assert "Exit code is 137." in sym.embed_text


def test_respects_max_chars():
    paras = "\n\n".join(f"Paragraph number {i} with some padding text." for i in range(60))
    doc = f"# Big\n\n## Section\n\n{paras}\n"
    chunks = chunk_document("KB-BIG", doc, max_chars=300, overlap_chars=50)
    assert len(chunks) > 1
    assert all(len(c.text) <= 300 + 50 for c in chunks)  # small tolerance for overlap seam


def test_overlap_carries_context():
    paras = "\n\n".join(f"Unique sentence {i} for overlap checking." for i in range(30))
    doc = f"## S\n\n{paras}\n"
    chunks = chunk_document("KB-OV", doc, max_chars=250, overlap_chars=120)
    assert len(chunks) >= 2
    # some tail of chunk N should reappear at the head of chunk N+1
    joined_next = chunks[1].text
    tail = chunks[0].text[-60:]
    assert any(word in joined_next for word in tail.split()[:5])


def test_oversize_paragraph_hard_split():
    """A single paragraph longer than max_chars must still be split — the
    pathological input a naive paragraph-packer silently mishandles."""
    monster = "x" * 5000
    doc = f"## Wall\n\n{monster}\n"
    chunks = chunk_document("KB-WALL", doc, max_chars=1000, overlap_chars=0)
    assert len(chunks) >= 5
    assert all(len(c.text) <= 1000 for c in chunks)


def test_empty_document_yields_nothing():
    assert chunk_document("KB-EMPTY", "") == []
