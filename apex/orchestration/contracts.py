"""Core orchestration contracts.

These contracts are intentionally generic so they apply to all current and
future primitives/connectors without scenario hardcoding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowPhase(str, Enum):
    INIT = "init"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OutcomeContract:
    """User-intent outcome that defines done-ness for a workflow."""

    user_request: str
    required_artifact_hints: List[str] = field(default_factory=list)
    required_side_effect_hints: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionPolicy:
    """Execution policy to keep orchestration safe and performant."""

    mode: str = "balanced"  # strict | balanced | fast
    max_llm_calls: int = 20
    max_tool_calls: int = 80
    max_wall_time_seconds: int = 180
    max_parallel_read_calls: int = 4


@dataclass
class WorkflowState:
    """Canonical orchestration state for a single workflow run."""

    workflow_id: str
    session_id: str
    phase: WorkflowPhase = WorkflowPhase.INIT
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    outcome: Optional[OutcomeContract] = None
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    llm_calls: int = 0
    tool_calls: int = 0
    last_error: Optional[str] = None

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "session_id": self.session_id,
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "last_error": self.last_error,
            "policy": {
                "mode": self.policy.mode,
                "max_llm_calls": self.policy.max_llm_calls,
                "max_tool_calls": self.policy.max_tool_calls,
                "max_wall_time_seconds": self.policy.max_wall_time_seconds,
                "max_parallel_read_calls": self.policy.max_parallel_read_calls,
            },
            "outcome": {
                "user_request": self.outcome.user_request,
                "required_artifact_hints": self.outcome.required_artifact_hints,
                "required_side_effect_hints": self.outcome.required_side_effect_hints,
                "constraints": self.outcome.constraints,
            }
            if self.outcome
            else None,
        }
