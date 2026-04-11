"""Benchmark runner for orchestration quality.

Runs synthetic or replay-derived snapshots through the evaluator and quality
gate so we can trend quality and enforce release criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List

from .evaluator import (
    EvaluationResult,
    QualityGateThresholds,
    check_quality_gate,
    evaluate_runtime_snapshot,
)


@dataclass
class BenchmarkCase:
    name: str
    llm_calls: int
    tool_calls: int
    wall_time_ms: float
    verification: Dict[str, Any]


def default_benchmark_cases() -> List[BenchmarkCase]:
    """Baseline orchestration benchmark suite.

    These are generic quality exemplars, not scenario hardcoding.
    """
    return [
        BenchmarkCase(
            name="fast_read_lookup",
            llm_calls=2,
            tool_calls=4,
            wall_time_ms=4500,
            verification={"satisfied": True, "score": 0.95},
        ),
        BenchmarkCase(
            name="standard_multi_step",
            llm_calls=7,
            tool_calls=14,
            wall_time_ms=13500,
            verification={"satisfied": True, "score": 0.9},
        ),
        BenchmarkCase(
            name="high_churn_warning",
            llm_calls=19,
            tool_calls=38,
            wall_time_ms=42000,
            verification={"satisfied": False, "score": 0.42},
        ),
    ]


def load_cases_from_json(path: str | Path) -> List[BenchmarkCase]:
    p = Path(path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    cases = payload.get("cases", payload)
    out: List[BenchmarkCase] = []
    for c in cases:
        out.append(
            BenchmarkCase(
                name=str(c.get("name", "unnamed_case")),
                llm_calls=int(c.get("llm_calls", 0)),
                tool_calls=int(c.get("tool_calls", 0)),
                wall_time_ms=float(c.get("wall_time_ms", 0.0)),
                verification=dict(c.get("verification", {})),
            )
        )
    return out


def run_benchmarks(
    cases: List[BenchmarkCase],
    thresholds: QualityGateThresholds | None = None,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    passed = 0

    for case in cases:
        ev: EvaluationResult = evaluate_runtime_snapshot(
            llm_calls=case.llm_calls,
            tool_calls=case.tool_calls,
            wall_time_ms=case.wall_time_ms,
            verification=case.verification,
        )
        gate = check_quality_gate(ev, thresholds=thresholds)
        if gate["passed"]:
            passed += 1
        rows.append(
            {
                "name": case.name,
                "evaluation": ev.to_dict(),
                "gate": gate,
            }
        )

    total = len(cases)
    pass_rate = (passed / total) if total else 0.0
    avg_score = (
        sum(r["evaluation"]["score"] for r in rows) / total
        if total
        else 0.0
    )

    return {
        "total": total,
        "passed": passed,
        "pass_rate": pass_rate,
        "avg_score": avg_score,
        "rows": rows,
    }
