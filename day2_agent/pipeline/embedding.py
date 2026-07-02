"""Embedding providers behind one small interface.

The `Embedder` protocol is the seam that makes the model backend swappable
(Ollama today, a hosted API tomorrow) without touching the pipeline or the index.
The index records (model_id, dim) and refuses to mix vector spaces — vectors from
different models are not comparable (FUNDAMENTALS ch.3).
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

from common.config import settings


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def dim(self) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaEmbedder:
    """Embeds via Ollama's native /api/embed endpoint (nomic-embed-text: 768 dims)."""

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 batch_size: int = 32, timeout_s: float = 120.0) -> None:
        self._model = model or settings.embed_model
        self._base = (base_url or settings.ollama_base_url).rstrip("/")
        self._batch = batch_size
        self._client = httpx.Client(timeout=timeout_s)
        self._dim: int | None = None

    @property
    def model_id(self) -> str:
        return f"ollama/{self._model}"

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = len(self.embed(["dimension probe"])[0])
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            resp = self._client.post(
                f"{self._base}/api/embed",
                json={"model": self._model, "input": batch},
            )
            resp.raise_for_status()
            embeddings = resp.json()["embeddings"]
            if len(embeddings) != len(batch):
                raise RuntimeError("Ollama returned a mismatched number of embeddings")
            out.extend(embeddings)
        if out and self._dim is None:
            self._dim = len(out[0])
        return out


class FakeEmbedder:
    """Deterministic, dependency-free embedder for tests and offline CI.

    Bag-of-hashed-words: each token deterministically activates a few dimensions,
    so texts sharing vocabulary genuinely land near each other under cosine —
    enough signal to test retrieval end-to-end without a model.
    """

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    @property
    def model_id(self) -> str:
        return f"fake/bag-of-hashed-words-{self._dim}"

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = hashlib.sha256(tok.encode()).digest()
            for j in range(3):
                idx = int.from_bytes(h[j * 4 : j * 4 + 4], "little") % self._dim
                sign = 1.0 if h[16 + j] % 2 == 0 else -1.0
                v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


def get_embedder(fake: bool = False) -> Embedder:
    return FakeEmbedder() if fake else OllamaEmbedder()
