"""Persist every triage run: the raw material for metrics, debugging, and for
growing the eval dataset from real traffic later."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from common.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    ticket TEXT NOT NULL,
    category TEXT,
    suggested_reply TEXT,
    citations TEXT,
    confidence REAL,
    latency_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    error TEXT
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init(db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    conn.close()


def record_run(
    *,
    ticket: str,
    result: dict | None,
    latency_ms: float,
    usage: dict | None = None,
    error: str | None = None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    usage = usage or {}
    conn.execute(
        "INSERT INTO runs (ts, ticket, category, suggested_reply, citations, confidence,"
        " latency_ms, prompt_tokens, completion_tokens, error)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            time.time(),
            ticket,
            (result or {}).get("category"),
            (result or {}).get("suggested_reply"),
            json.dumps((result or {}).get("citations")) if result else None,
            (result or {}).get("confidence"),
            latency_ms,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            error,
        ),
    )
    conn.commit()
    conn.close()
