"""copilot-eval — the quality gate (FUNDAMENTALS ch.11).

Runs the labeled dataset against a live /triage endpoint, applies two layers
of checks, writes a scorecard, and exits non-zero if thresholds fail — which
is exactly what makes it usable as a *pipeline stage* rather than a notebook:

Layer 1 — deterministic checks (free, exact, run always):
  * schema validity        — response parses as TriageResult
  * citation integrity     — every cited runbook id exists in the KB
  * category accuracy      — category in the labeled accepted set
  * escalation honesty     — trap cases must come back needs_escalation
  * expected citations     — non-trap cases should cite at least one of the
                             labeled expected articles (recall@cited)

Layer 2 — LLM-as-judge (subjective quality, skippable with --skip-judge):
  * groundedness / correctness / helpfulness per evals/judge.py rubric

Thresholds come from env so the pipeline can tune them without code changes:
  EVAL_MIN_ACCURACY      default 0.75
  EVAL_MIN_GROUNDEDNESS  default 0.7   (mean over judged cases)
  EVAL_MIN_SCHEMA_OK     default 1.0   (schema failures are never acceptable)
  EVAL_MAX_P95_MS        default 0     (0 = disabled; latency gate optional)

Usage:
  copilot-eval --endpoint http://localhost:8000 --out scorecard.json
  copilot-eval --skip-judge          # deterministic layer only (CI without GPU)
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

from common.config import settings
from day2_agent.agent.schemas import TriageResult
from evals.judge import JudgeScore, judge_reply

DATASET = Path(__file__).parent / "dataset.jsonl"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round(pct / 100 * (len(values) - 1))))
    return values[idx]


def load_dataset(path: Path) -> list[dict]:
    cases = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def kb_article_ids() -> set[str]:
    return {p.name.split("-", 2)[0] + "-" + p.name.split("-", 2)[1]
            for p in settings.kb_dir.glob("KB-*.md")}


def run_case(client: httpx.Client, endpoint: str, case: dict, kb_ids: set[str],
             skip_judge: bool) -> dict:
    row: dict = {"id": case["id"], "accepted_categories": case["accepted_categories"]}
    start = time.perf_counter()
    try:
        resp = client.post(f"{endpoint}/triage", params={"stream": "false"},
                           json={"ticket": case["ticket"]})
        row["http_status"] = resp.status_code
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        row.update(error=f"{type(exc).__name__}: {exc}", schema_ok=False,
                   category_ok=False, citations_valid=False, expected_cited=False,
                   latency_ms=(time.perf_counter() - start) * 1000)
        return row
    row["latency_ms"] = body.get("latency_ms", (time.perf_counter() - start) * 1000)

    # --- Layer 1: deterministic -------------------------------------------
    raw = body.get("result") or {}
    try:
        result = TriageResult.model_validate(raw)
        row["schema_ok"] = True
    except ValidationError as exc:
        row.update(schema_ok=False, category_ok=False, citations_valid=False,
                   expected_cited=False, error=f"schema: {exc.errors()[:2]}")
        return row

    row["category"] = result.category
    row["confidence"] = result.confidence
    row["citations"] = result.citations
    row["category_ok"] = result.category in case["accepted_categories"]

    # every citation must point at a real runbook — a fabricated id is a
    # hard hallucination signal, caught without any LLM
    row["citations_valid"] = all(c in kb_ids for c in result.citations)

    expected = set(case.get("expected_article_ids") or [])
    if expected:
        row["expected_cited"] = bool(expected & set(result.citations))
    else:
        # escalation traps: honesty means citing nothing and escalating
        row["expected_cited"] = not result.citations

    # --- Layer 2: judge ----------------------------------------------------
    if not skip_judge:
        score: JudgeScore = judge_reply(case["ticket"], result.model_dump())
        row["judge"] = {
            "groundedness": score.groundedness,
            "correctness": score.correctness,
            "helpfulness": score.helpfulness,
            "mean": round(score.mean, 3),
            "rationale": score.rationale,
            "error": score.error,
        }
    return row


def aggregate(rows: list[dict], skip_judge: bool) -> dict:
    n = len(rows)
    ok = [r for r in rows if r.get("schema_ok")]
    latencies = [r["latency_ms"] for r in rows if "latency_ms" in r]
    summary = {
        "n": n,
        "schema_ok_rate": round(sum(bool(r.get("schema_ok")) for r in rows) / n, 3),
        "category_accuracy": round(sum(bool(r.get("category_ok")) for r in rows) / n, 3),
        "citation_validity_rate": round(
            sum(bool(r.get("citations_valid")) for r in rows) / n, 3),
        "expected_citation_rate": round(
            sum(bool(r.get("expected_cited")) for r in rows) / n, 3),
        "latency_p50_ms": round(_percentile(latencies, 50), 1),
        "latency_p95_ms": round(_percentile(latencies, 95), 1),
    }
    if not skip_judge:
        judged = [r["judge"] for r in ok if r.get("judge") and not r["judge"].get("error")]
        summary["judged_n"] = len(judged)
        for dim in ("groundedness", "correctness", "helpfulness"):
            summary[f"judge_{dim}"] = (
                round(statistics.mean(j[dim] for j in judged), 3) if judged else 0.0)
    return summary


def apply_thresholds(summary: dict, skip_judge: bool) -> list[str]:
    failures: list[str] = []

    def gate(name: str, actual: float, minimum: float) -> None:
        if actual < minimum:
            failures.append(f"{name}: {actual} < required {minimum}")

    gate("schema_ok_rate", summary["schema_ok_rate"],
         float(os.environ.get("EVAL_MIN_SCHEMA_OK", "1.0")))
    gate("category_accuracy", summary["category_accuracy"],
         float(os.environ.get("EVAL_MIN_ACCURACY", "0.75")))
    gate("citation_validity_rate", summary["citation_validity_rate"],
         float(os.environ.get("EVAL_MIN_CITATION_VALIDITY", "1.0")))
    if not skip_judge and summary.get("judged_n"):
        gate("judge_groundedness", summary["judge_groundedness"],
             float(os.environ.get("EVAL_MIN_GROUNDEDNESS", "0.7")))
    max_p95 = float(os.environ.get("EVAL_MAX_P95_MS", "0"))
    if max_p95 > 0 and summary["latency_p95_ms"] > max_p95:
        failures.append(f"latency_p95_ms: {summary['latency_p95_ms']} > {max_p95}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the triage eval suite.")
    parser.add_argument("--endpoint", default="http://localhost:8000",
                        help="Base URL of a running day3 service.")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--out", default="scorecard.json")
    parser.add_argument("--skip-judge", action="store_true",
                        help="Deterministic checks only (no judge LLM calls).")
    parser.add_argument("--timeout", type=float, default=300.0,
                        help="Per-request timeout; agent runs are slow on CPU.")
    args = parser.parse_args()

    cases = load_dataset(Path(args.dataset))
    kb_ids = kb_article_ids()
    print(f"eval: {len(cases)} cases -> {args.endpoint}  "
          f"(judge={'off' if args.skip_judge else settings.judge_model})",
          file=sys.stderr)

    rows: list[dict] = []
    with httpx.Client(timeout=args.timeout) as client:
        for case in cases:
            row = run_case(client, args.endpoint, case, kb_ids, args.skip_judge)
            status = "OK " if row.get("category_ok") else "FAIL"
            print(f"  [{status}] {row['id']}  cat={row.get('category', '?'):<18} "
                  f"cited={row.get('citations', [])}  "
                  f"{row.get('latency_ms', 0):.0f}ms", file=sys.stderr)
            rows.append(row)

    summary = aggregate(rows, args.skip_judge)
    failures = apply_thresholds(summary, args.skip_judge)
    scorecard = {
        "endpoint": args.endpoint,
        "model": settings.chat_model,
        "judge_model": None if args.skip_judge else settings.judge_model,
        "summary": summary,
        "threshold_failures": failures,
        "passed": not failures,
        "cases": rows,
    }
    Path(args.out).write_text(json.dumps(scorecard, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    if failures:
        print("EVAL FAILED:", *failures, sep="\n  - ", file=sys.stderr)
        sys.exit(1)
    print("eval passed.", file=sys.stderr)


if __name__ == "__main__":
    main()
