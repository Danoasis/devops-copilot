"""Index + ingest tests. These use FakeEmbedder (deterministic bag-of-hashed-
words) so they exercise the REAL sqlite-vec storage/search path with zero
Ollama dependency — exactly what runs in the pipeline's CI stage."""
import pytest

from day2_agent.pipeline.embedding import FakeEmbedder
from day2_agent.pipeline.index import VectorIndex
from day2_agent.pipeline.ingest import run_ingest


@pytest.fixture()
def kb(tmp_path):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "KB-101-oomkilled.md").write_text(
        "# OOMKilled\n\n## Symptoms\n\nContainer exits with code 137, "
        "reason OOMKilled, memory limit exceeded.\n\n## Fix\n\nProfile memory "
        "usage then raise the limit.\n", encoding="utf-8")
    (kb_dir / "KB-102-certificates.md").write_text(
        "# Certificate expiry\n\n## Symptoms\n\nTLS handshake fails, "
        "certificate date invalid.\n\n## Fix\n\nRenew and rotate the "
        "certificate, automate with cert-manager.\n", encoding="utf-8")
    return kb_dir


@pytest.fixture()
def index(tmp_path):
    idx = VectorIndex(tmp_path / "test.db", FakeEmbedder())
    yield idx
    idx.close()


def test_ingest_and_search_relevance(kb, index):
    report = run_ingest(kb, index)
    assert report.ingested == 2
    assert report.chunks_written > 0

    hits = index.search("container killed exit code 137 memory", k=3)
    assert hits, "search returned nothing"
    assert hits[0].doc_id == "KB-101", f"expected OOM doc first, got {hits[0].doc_id}"

    hits = index.search("TLS certificate expired handshake", k=3)
    assert hits[0].doc_id == "KB-102"


def test_reingest_is_idempotent(kb, index):
    run_ingest(kb, index)
    second = run_ingest(kb, index)
    assert second.ingested == 0
    assert second.skipped == 2, "unchanged files must be hash-skipped"


def test_changed_file_reingested(kb, index):
    run_ingest(kb, index)
    f = kb / "KB-101-oomkilled.md"
    f.write_text(f.read_text(encoding="utf-8") + "\n\nNew paragraph.\n", encoding="utf-8")
    report = run_ingest(kb, index)
    assert report.ingested == 1
    assert report.skipped == 1


def test_deleted_file_reconciled(kb, index):
    """Ingest is a reconciliation loop, not append-only: docs whose source
    file disappeared must be removed (same idea as `kubectl apply`)."""
    run_ingest(kb, index)
    (kb / "KB-102-certificates.md").unlink()
    report = run_ingest(kb, index)
    assert report.removed == 1
    assert all(h.doc_id != "KB-102" for h in index.search("certificate", k=5))


def test_rebuild_flag(kb, index):
    run_ingest(kb, index)
    report = run_ingest(kb, index, rebuild=True)
    assert report.ingested == 2, "rebuild must force re-embedding everything"


def test_embedder_mismatch_rejected(kb, tmp_path):
    """The index pins (embed_model, dim). Opening it with a different
    embedder must fail loudly — mixing vector spaces silently corrupts
    search instead of erroring, which is far worse."""
    db = tmp_path / "pinned.db"
    idx = VectorIndex(db, FakeEmbedder(dim=64))
    run_ingest(kb, idx)
    idx.close()

    with pytest.raises(Exception, match="(?i)mismatch|rebuild"):
        VectorIndex(db, FakeEmbedder(dim=32))


def test_stats(kb, index):
    run_ingest(kb, index)
    stats = index.stats()
    assert stats["documents"] == 2
    assert stats["chunks"] >= 2
