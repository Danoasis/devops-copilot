"""The production-shaped wrapper around the agent (FUNDAMENTALS ch.5).

POST /triage        — run the agent; ?stream=true (default) returns SSE events
                      (iterations, tool calls, final result) as they happen;
                      ?stream=false returns one JSON object (used by the eval).
GET  /healthz       — liveness: the process is up.
GET  /readyz        — readiness: Ollama is reachable (gates K8s traffic).
GET  /metrics       — Prometheus exposition.

Concurrency guardrails: a semaphore bounds concurrent agent runs (backpressure);
every LLM/tool call inside the loop already has timeouts. One MCP session is
opened per request — stdio sessions are cheap and it keeps requests isolated."""
from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field

from common.config import settings
from day2_agent.agent.loop import AgentError, run_triage
from day3_service.app import store
from day3_service.app.telemetry import setup_tracing

MAX_CONCURRENT_TRIAGES = int(os.environ.get("MAX_CONCURRENT_TRIAGES", "4"))

TRIAGE_REQUESTS = Counter("triage_requests_total", "Triage requests", ["outcome"])
TRIAGE_DURATION = Histogram(
    "triage_duration_seconds", "End-to-end triage latency",
    buckets=(1, 2.5, 5, 10, 20, 40, 80, 160),
)
LLM_TOKENS = Counter("llm_tokens_total", "LLM tokens used", ["kind"])
IN_FLIGHT = Gauge("triage_in_flight", "Triage requests currently running")


class TicketIn(BaseModel):
    ticket: str = Field(min_length=10, description="The raw support ticket text.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_tracing()
    store.init()
    app.state.semaphore = asyncio.Semaphore(MAX_CONCURRENT_TRIAGES)
    yield


app = FastAPI(title="DevOps Copilot", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    """Ready = our model backend answers. Readiness (not liveness!) checks the
    dependency, so a down Ollama drains traffic without restart storms."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        return JSONResponse({"status": "not ready", "reason": str(exc)}, status_code=503)


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _run_once(ticket: str, emit) -> tuple[dict | None, dict, str | None]:
    """Run one triage; returns (result_dict, usage, error)."""
    usage: dict = {}

    def on_event(event: dict) -> None:
        if event.get("type") == "usage":
            usage.update({k: v for k, v in event.items() if k != "type"})
        emit(event)

    try:
        result = await run_triage(ticket, on_event=on_event)
        return result.model_dump(), usage, None
    except AgentError as exc:
        return None, usage, str(exc)


@app.post("/triage")
async def triage(body: TicketIn, stream: bool = Query(default=True)):
    sem: asyncio.Semaphore = app.state.semaphore

    if not stream:
        start = time.perf_counter()
        async with sem:
            IN_FLIGHT.inc()
            try:
                result, usage, error = await _run_once(body.ticket, lambda e: None)
            finally:
                IN_FLIGHT.dec()
        latency_ms = (time.perf_counter() - start) * 1000
        _finalize_metrics(result, usage, error, latency_ms)
        store.record_run(ticket=body.ticket, result=result, latency_ms=latency_ms,
                         usage=usage, error=error)
        if error:
            return JSONResponse({"error": error}, status_code=502)
        return JSONResponse({"result": result, "latency_ms": round(latency_ms, 1),
                             "usage": usage})

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()
        start = time.perf_counter()

        async def work():
            async with sem:
                IN_FLIGHT.inc()
                try:
                    return await _run_once(body.ticket, queue.put_nowait)
                finally:
                    IN_FLIGHT.dec()

        task = asyncio.create_task(work())
        try:
            while True:
                get_event = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait(
                    {task, get_event}, return_when=asyncio.FIRST_COMPLETED
                )
                if get_event in done:
                    yield f"data: {json.dumps(get_event.result())}\n\n"
                    continue
                get_event.cancel()
                break
            result, usage, error = task.result()
            while not queue.empty():  # drain trailing events
                yield f"data: {json.dumps(queue.get_nowait())}\n\n"
            latency_ms = (time.perf_counter() - start) * 1000
            _finalize_metrics(result, usage, error, latency_ms)
            store.record_run(ticket=body.ticket, result=result, latency_ms=latency_ms,
                             usage=usage, error=error)
            final = {"type": "result", "result": result, "error": error,
                     "latency_ms": round(latency_ms, 1), "usage": usage}
            yield f"data: {json.dumps(final)}\n\n"
        except asyncio.CancelledError:  # client disconnected
            task.cancel()
            raise

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _finalize_metrics(result, usage, error, latency_ms: float) -> None:
    TRIAGE_DURATION.observe(latency_ms / 1000)
    TRIAGE_REQUESTS.labels(outcome="error" if error else "ok").inc()
    if usage.get("prompt_tokens"):
        LLM_TOKENS.labels(kind="prompt").inc(usage["prompt_tokens"])
    if usage.get("completion_tokens"):
        LLM_TOKENS.labels(kind="completion").inc(usage["completion_tokens"])
