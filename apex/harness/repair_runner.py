"""Repair runner contract for generic fix-and-rerun workflows.

This module intentionally defines contracts and planning metadata only.
It does not apply code changes directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List
import uuid


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RepairRequest:
    """A queued repair attempt derived from diagnosed failures."""

    id: str
    created_at: str
    status: str
    source_run_id: str
    scenario_ids: List[str]
    strategy: str
    max_fix_attempts: int
    auto_rerun: bool
    notes: str
    failure_categories: List[str]
    eligible_failures: List[Dict[str, Any]]
    blocked_failures: List[Dict[str, Any]]
    recommended_actions: List[str]
    rerun_plan: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "status": self.status,
            "source_run_id": self.source_run_id,
            "scenario_ids": self.scenario_ids,
            "strategy": self.strategy,
            "max_fix_attempts": self.max_fix_attempts,
            "auto_rerun": self.auto_rerun,
            "notes": self.notes,
            "failure_categories": self.failure_categories,
            "eligible_failures": self.eligible_failures,
            "blocked_failures": self.blocked_failures,
            "recommended_actions": self.recommended_actions,
            "rerun_plan": self.rerun_plan,
        }


ELIGIBLE_CATEGORIES = {
    "tool_failed",
    "missing_output",
    "missing_tool",
    "connector_error",
    "configuration",
}

BLOCKED_CATEGORIES = {
    "auth_failed",
    "connector_unavailable",
    "rate_limited",
    "approval_timeout",
    "unknown",
}


def build_repair_request(
    *,
    source_run_id: str,
    diagnosed_failures: List[Dict[str, Any]],
    strategy: str,
    max_fix_attempts: int,
    auto_rerun: bool,
    notes: str,
) -> RepairRequest:
    """Create a generic repair contract from diagnosed failures.

    The contract indicates which failures are safe for automated remediation
    and what rerun should happen after attempted fixes.
    """

    scenario_ids = sorted({item.get("scenario_id") for item in diagnosed_failures if item.get("scenario_id")})
    eligible: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    categories = sorted({str(item.get("category", "unknown")) for item in diagnosed_failures})

    for failure in diagnosed_failures:
        category = str(failure.get("category", "unknown"))
        confidence = float(failure.get("confidence", 0.0) or 0.0)
        remediable = bool(failure.get("is_remediable", False))

        record = {
            "scenario_id": failure.get("scenario_id"),
            "scenario_name": failure.get("scenario_name"),
            "category": category,
            "confidence": confidence,
            "issues": failure.get("issues", [])[:5],
            "next_steps": failure.get("next_steps", [])[:5],
        }

        if category in ELIGIBLE_CATEGORIES and (remediable or confidence >= 0.7):
            eligible.append(record)
        else:
            blocked.append(record)

    recommended_actions = [
        "Apply only generic fixes in primitives/connectors/orchestration/evaluator layers",
        "Avoid scenario-specific prompt or tool routing rules",
        "Run targeted rerun after each accepted fix",
    ]
    if any(item.get("category") in BLOCKED_CATEGORIES for item in blocked):
        recommended_actions.append("Escalate blocked auth/rate-limit/environment failures to operator")

    rerun_plan = {
        "type": "scenario",
        "scenario_ids": scenario_ids,
        "iterations": 1,
        "rerun_failed_only": True,
        "auto_approve": True,
    }

    return RepairRequest(
        id=f"repair-{uuid.uuid4().hex[:12]}",
        created_at=utc_now(),
        status="queued",
        source_run_id=source_run_id,
        scenario_ids=scenario_ids,
        strategy=strategy,
        max_fix_attempts=max(1, int(max_fix_attempts)),
        auto_rerun=bool(auto_rerun),
        notes=notes,
        failure_categories=categories,
        eligible_failures=eligible,
        blocked_failures=blocked,
        recommended_actions=recommended_actions,
        rerun_plan=rerun_plan,
    )