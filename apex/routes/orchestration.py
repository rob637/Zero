"""Orchestration quality and benchmark routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from orchestration import (
    BenchmarkCase,
    QualityGateThresholds,
    default_benchmark_cases,
    run_benchmarks,
)

router = APIRouter(prefix="/orchestration", tags=["orchestration"])


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
