"""SQLite + sqlite-vec vector index.

Brute-force exact cosine search over a virtual table — the honest choice at this
corpus size (FUNDAMENTALS ch.3: 'knowing when you don't need HNSW is the senior
signal'). The index versions its embedding space (model_id, dim) in a meta table
and refuses to mix incompatible vectors.
"""
from __future__ import annotations

import sqlite3
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from day2_agent.pipeline.chunker import Chunk
from day2_agent.pipeline.embedding import Embedder


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    doc_id: str
    heading: str
    text: str
    score: float  # 1 - cosine_distance; higher is closer


def _serialize(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


class VectorIndex:
    def __init__(self, db_path: Path, embedder: Embedder) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.db = sqlite3.connect(self.db_path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self._ensure_schema()

    # --- schema -----------------------------------------------------------
    def _ensure_schema(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                title TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
                heading TEXT NOT NULL,
                text TEXT NOT NULL
            );
            """
        )
        stored_model = self._meta("embed_model")
        stored_dim = self._meta("embed_dim")
        if stored_model is None:
            # First use: bind this index to the embedder's vector space.
            dim = self.embedder.dim
            self.db.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING "
                f"vec0(embedding float[{dim}] distance_metric=cosine)"
            )
            self._set_meta("embed_model", self.embedder.model_id)
            self._set_meta("embed_dim", str(dim))
            self.db.commit()
        elif stored_model != self.embedder.model_id or int(stored_dim or 0) != self.embedder.dim:
            raise RuntimeError(
                f"Index at {self.db_path} was built with {stored_model} ({stored_dim} dims) "
                f"but the configured embedder is {self.embedder.model_id} "
                f"({self.embedder.dim} dims). Vectors from different models are not "
                f"comparable — re-ingest with:  copilot-ingest --rebuild"
            )

    def _meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # --- writes -----------------------------------------------------------
    def doc_hash(self, doc_id: str) -> str | None:
        row = self.db.execute(
            "SELECT content_hash FROM documents WHERE doc_id=?", (doc_id,)
        ).fetchone()
        return row[0] if row else None

    def delete_document(self, doc_id: str) -> None:
        ids = [r[0] for r in self.db.execute(
            "SELECT chunk_id FROM chunks WHERE doc_id=?", (doc_id,)
        )]
        if ids:
            qmarks = ",".join("?" * len(ids))
            self.db.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({qmarks})", ids)
            self.db.execute(f"DELETE FROM chunks WHERE chunk_id IN ({qmarks})", ids)
        self.db.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
        self.db.commit()

    def upsert_document(
        self, doc_id: str, path: str, title: str, content_hash: str, chunks: list[Chunk]
    ) -> int:
        """Replace a document's chunks and vectors. Returns chunk count."""
        self.delete_document(doc_id)
        self.db.execute(
            "INSERT INTO documents(doc_id, path, title, content_hash, updated_at) "
            "VALUES (?,?,?,?,?)",
            (doc_id, path, title, content_hash, time.time()),
        )
        vectors = self.embedder.embed([c.embed_text for c in chunks])
        for chunk, vec in zip(chunks, vectors):
            cur = self.db.execute(
                "INSERT INTO chunks(doc_id, heading, text) VALUES (?,?,?)",
                (chunk.doc_id, chunk.heading, chunk.text),
            )
            self.db.execute(
                "INSERT INTO vec_chunks(rowid, embedding) VALUES (?,?)",
                (cur.lastrowid, _serialize(vec)),
            )
        self.db.commit()
        return len(chunks)

    # --- reads ------------------------------------------------------------
    def search(self, query: str, k: int = 5) -> list[Hit]:
        qvec = self.embedder.embed([query])[0]
        rows = self.db.execute(
            """
            SELECT c.chunk_id, c.doc_id, c.heading, c.text, v.distance
            FROM vec_chunks v JOIN chunks c ON c.chunk_id = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            (_serialize(qvec), k),
        ).fetchall()
        return [
            Hit(chunk_id=r[0], doc_id=r[1], heading=r[2], text=r[3], score=round(1.0 - r[4], 4))
            for r in rows
        ]

    def stats(self) -> dict:
        docs = self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {
            "documents": docs,
            "chunks": chunks,
            "embed_model": self._meta("embed_model"),
            "embed_dim": self._meta("embed_dim"),
        }

    def close(self) -> None:
        self.db.close()
