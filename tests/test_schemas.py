"""Schema tests — the structured-output contract — plus unit tests for the
eval's deterministic layer (which must be trustworthy enough to gate deploys
without any LLM in the loop)."""
import pytest
from pydantic import ValidationError

from day2_agent.agent.schemas import IncidentReport, TriageResult, schema_prompt
from evals.judge import _extract_json, _snap
from evals.run_eval import _percentile, aggregate


def test_valid_triage_result():
    r = TriageResult(
        category="kubernetes",
        suggested_reply="Check `kubectl logs --previous` per KB-001.",
        citations=["KB-001"],
        confidence=0.85,
    )
    assert r.category == "kubernetes"


def test_category_literal_enforced():
    with pytest.raises(ValidationError):
        TriageResult(category="networking", suggested_reply="x", citations=[], confidence=0.5)


def test_confidence_bounds():
    with pytest.raises(ValidationError):
        TriageResult(category="ci_cd", suggested_reply="x", citations=[], confidence=1.5)
    with pytest.raises(ValidationError):
        TriageResult(category="ci_cd", suggested_reply="x", citations=[], confidence=-0.1)


def test_model_validate_from_llm_style_dict():
    """Simulates what run_agent does after _extract_json."""
    raw = {"category": "observability", "suggested_reply": "See KB-007.",
           "citations": ["KB-007"], "confidence": 0.7}
    assert TriageResult.model_validate(raw).citations == ["KB-007"]


def test_schema_prompt_contains_enum():
    prompt = schema_prompt(TriageResult)
    assert "needs_escalation" in prompt
    assert "confidence" in prompt


def test_incident_report_fields():
    r = IncidentReport(
        deployment="web-frontend", root_cause="bad image tag",
        evidence=["Failed to pull image"], cited_runbooks=["KB-002"],
        recommended_fix="fix tag", remediation_command="kubectl set image ...",
        confidence=0.9,
    )
    assert r.deployment == "web-frontend"


# --- eval helpers -----------------------------------------------------------

def test_judge_json_extraction_tolerates_fences():
    fenced = '```json\n{"groundedness": 1, "correctness": 0.5, "helpfulness": 1, "rationale": "ok"}\n```'
    assert _extract_json(fenced)["correctness"] == 0.5


def test_judge_score_snaps_to_anchors():
    assert _snap(0.9) == 1.0
    assert _snap(0.3) == 0.5
    assert _snap(0.1) == 0.0
    assert _snap("garbage") == 0.0


def test_percentile():
    assert _percentile([], 95) == 0.0
    assert _percentile([100.0], 95) == 100.0
    vals = [float(i) for i in range(1, 101)]
    assert _percentile(vals, 50) == pytest.approx(50.0, abs=2)
    assert _percentile(vals, 95) == pytest.approx(95.0, abs=2)


def test_aggregate_counts_failures_against_accuracy():
    rows = [
        {"schema_ok": True, "category_ok": True, "citations_valid": True,
         "expected_cited": True, "latency_ms": 100.0},
        {"schema_ok": False, "category_ok": False, "citations_valid": False,
         "expected_cited": False, "latency_ms": 50.0},
    ]
    s = aggregate(rows, skip_judge=True)
    assert s["n"] == 2
    assert s["schema_ok_rate"] == 0.5
    assert s["category_accuracy"] == 0.5
