"""Outcome verifier for orchestration completion quality.

The verifier checks whether execution likely satisfied user intent contracts,
without hardcoding specific workflows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .artifact_ledger import ArtifactRecord
from .contracts import OutcomeContract


@dataclass
class VerificationResult:
    satisfied: bool
    score: float
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "satisfied": self.satisfied,
            "score": self.score,
            "issues": self.issues,
            "recommendations": self.recommendations,
        }


def verify_outcome(
    outcome: OutcomeContract | None,
    agent_state: Any,
    artifacts: Sequence[ArtifactRecord],
) -> VerificationResult:
    """Verify workflow outcome based on generic contracts and execution evidence."""

    if outcome is None:
        return VerificationResult(
            satisfied=True,
            score=0.7,
            issues=[],
            recommendations=[],
        )

    issues: List[str] = []
    recommendations: List[str] = []
    score = 1.0

    pending = getattr(agent_state, "pending_approval", None)
    if pending is not None:
        issues.append("Workflow is waiting for user approval")
        recommendations.append("Approve or cancel pending action to continue")
        score -= 0.2

    if outcome.required_artifact_hints and len(artifacts) == 0:
        issues.append("No output artifacts were recorded")
        recommendations.append("Create/export an artifact before finalizing side-effects")
        score -= 0.35

    completed_side_effects = 0
    for step in getattr(agent_state, "steps", []) or []:
        if getattr(step, "status", None) is None:
            continue
        status_val = getattr(getattr(step, "status", None), "value", str(getattr(step, "status", "")))
        if status_val == "completed" and bool(getattr(step, "requires_approval", False)):
            completed_side_effects += 1

    if outcome.required_side_effect_hints and completed_side_effects == 0:
        issues.append("No side-effect action completed for requested outcome")
        recommendations.append("Execute or approve required action once evidence is ready")
        score -= 0.35

    llm_calls = int(getattr(agent_state, "llm_calls", 0) or 0)
    if llm_calls > 16:
        issues.append(f"High orchestration churn detected ({llm_calls} LLM calls)")
        recommendations.append("Trigger clarify/replan earlier when novelty drops")
        score -= 0.15

    score = max(0.0, min(1.0, score))
    return VerificationResult(
        satisfied=len(issues) == 0,
        score=score,
        issues=issues,
        recommendations=recommendations,
    )
