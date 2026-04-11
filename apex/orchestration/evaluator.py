"""Orchestration evaluator.

Provides a lightweight scoring model for run quality so we can baseline,
trend, and gate releases on objective metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class EvaluationResult:
    score: float
    success: bool
    efficiency: float
    latency: float
    churn: float
    notes: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "success": self.success,
            "efficiency": self.efficiency,
            "latency": self.latency,
            "churn": self.churn,
            "notes": self.notes,
        }


@dataclass
class QualityGateThresholds:
    min_score: float = 0.75
    min_efficiency: float = 0.25
    min_latency: float = 0.15
    min_churn: float = 0.15


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def evaluate_runtime_snapshot(
    *,
    llm_calls: int,
    tool_calls: int,
    wall_time_ms: float,
    verification: Dict[str, Any] | None = None,
) -> EvaluationResult:
    """Score orchestration run quality from core runtime indicators."""

    verification = verification or {}
    verified_score = float(verification.get("score", 0.7))
    verified_satisfied = bool(verification.get("satisfied", False))

    # Efficiency prefers fewer tool calls for a given objective.
    efficiency = _clamp(1.0 - (max(tool_calls, 0) / 80.0))
    # Latency target is 25s for multi-step tasks.
    latency = _clamp(1.0 - (max(wall_time_ms, 0.0) / 25000.0))
    # Churn penalizes large numbers of LLM calls.
    churn = _clamp(1.0 - (max(llm_calls, 0) / 20.0))

    # Weighted quality score.
    score = _clamp((0.45 * verified_score) + (0.2 * efficiency) + (0.2 * latency) + (0.15 * churn))

    return EvaluationResult(
        score=score,
        success=verified_satisfied and score >= 0.7,
        efficiency=efficiency,
        latency=latency,
        churn=churn,
        notes={
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "wall_time_ms": wall_time_ms,
            "verification_score": verified_score,
            "verification_satisfied": verified_satisfied,
        },
    )


def check_quality_gate(
    evaluation: EvaluationResult,
    thresholds: QualityGateThresholds | None = None,
) -> Dict[str, Any]:
    """Evaluate whether a run passes orchestration quality gate thresholds."""

    th = thresholds or QualityGateThresholds()
    failures = []
    if evaluation.score < th.min_score:
        failures.append(f"score<{th.min_score}")
    if evaluation.efficiency < th.min_efficiency:
        failures.append(f"efficiency<{th.min_efficiency}")
    if evaluation.latency < th.min_latency:
        failures.append(f"latency<{th.min_latency}")
    if evaluation.churn < th.min_churn:
        failures.append(f"churn<{th.min_churn}")

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "thresholds": {
            "min_score": th.min_score,
            "min_efficiency": th.min_efficiency,
            "min_latency": th.min_latency,
            "min_churn": th.min_churn,
        },
    }
