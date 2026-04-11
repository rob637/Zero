"""Orchestration quality and benchmark routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from orchestration import (
    BenchmarkCase,
    OrchestrationEvalStore,
    QualityGateThresholds,
    default_benchmark_cases,
    run_benchmarks,
)

router = APIRouter(prefix="/orchestration", tags=["orchestration"])
_eval_store = OrchestrationEvalStore(Path(__file__).resolve().parent.parent / "sqlite" / "orchestration.db")


class BenchmarkCaseRequest(BaseModel):
    name: str
    llm_calls: int
    tool_calls: int
    wall_time_ms: float
    verification: Dict[str, Any] = {}


class BenchmarkRunRequest(BaseModel):
    cases: Optional[List[BenchmarkCaseRequest]] = None
    thresholds: Optional[Dict[str, float]] = None


@router.get("/benchmarks/default")
async def orchestration_default_benchmarks():
    cases = [c.__dict__ for c in default_benchmark_cases()]
    return JSONResponse({"cases": cases})


@router.post("/benchmarks/run")
async def orchestration_run_benchmarks(req: BenchmarkRunRequest):
    input_cases = req.cases or [BenchmarkCaseRequest(**c.__dict__) for c in default_benchmark_cases()]
    cases = [
        BenchmarkCase(
            name=c.name,
            llm_calls=c.llm_calls,
            tool_calls=c.tool_calls,
            wall_time_ms=c.wall_time_ms,
            verification=c.verification,
        )
        for c in input_cases
    ]

    th = None
    if req.thresholds:
        th = QualityGateThresholds(
            min_score=float(req.thresholds.get("min_score", 0.75)),
            min_efficiency=float(req.thresholds.get("min_efficiency", 0.25)),
            min_latency=float(req.thresholds.get("min_latency", 0.15)),
            min_churn=float(req.thresholds.get("min_churn", 0.15)),
        )

    result = run_benchmarks(cases, thresholds=th)
    return JSONResponse(result)


@router.get("/quality/thresholds")
async def orchestration_quality_thresholds():
    th = QualityGateThresholds()
    return JSONResponse(
        {
            "min_score": th.min_score,
            "min_efficiency": th.min_efficiency,
            "min_latency": th.min_latency,
            "min_churn": th.min_churn,
        }
    )


@router.get("/quality/history")
async def orchestration_quality_history(limit: int = 50):
    rows = _eval_store.recent_runs(limit=max(1, min(limit, 500)))
    return JSONResponse(
        {
            "total": len(rows),
            "rows": [
                {
                    "run_id": r.run_id,
                    "workflow_id": r.workflow_id,
                    "session_id": r.session_id,
                    "request_text": r.request_text,
                    "created_at": r.created_at,
                    "score": r.score,
                    "success": r.success,
                    "passed_gate": r.passed_gate,
                    "llm_calls": r.llm_calls,
                    "tool_calls": r.tool_calls,
                    "wall_time_ms": r.wall_time_ms,
                }
                for r in rows
            ],
        }
    )


@router.get("/quality/release-gate")
async def orchestration_release_gate(lookback: int = 200):
    summary = _eval_store.summary(lookback=max(10, min(lookback, 2000)))

    total = int(summary.get("total", 0))
    pass_rate = float(summary.get("pass_rate", 0.0))
    avg_score = float(summary.get("avg_score", 0.0))
    avg_latency_ms = float(summary.get("avg_latency_ms", 0.0))

    # Generic release criteria for orchestration quality.
    criteria = {
        "min_total_runs": 30,
        "min_pass_rate": 0.90,
        "min_avg_score": 0.80,
        "max_avg_latency_ms": 30000.0,
    }

    failures: List[str] = []
    if total < criteria["min_total_runs"]:
        failures.append("insufficient_run_history")
    if pass_rate < criteria["min_pass_rate"]:
        failures.append("pass_rate_below_target")
    if avg_score < criteria["min_avg_score"]:
        failures.append("avg_score_below_target")
    if avg_latency_ms > criteria["max_avg_latency_ms"]:
        failures.append("avg_latency_above_target")

    return JSONResponse(
        {
            "ready": len(failures) == 0,
            "failures": failures,
            "criteria": criteria,
            "summary": summary,
        }
    )
