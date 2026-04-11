"""Generic orchestration state machine.

Encodes legal phase transitions so workflow behavior is deterministic even when
planner/executor decisions are LLM-driven.
"""

from __future__ import annotations

from typing import Dict, Set

from .contracts import WorkflowPhase, WorkflowState


_ALLOWED_TRANSITIONS: Dict[WorkflowPhase, Set[WorkflowPhase]] = {
    WorkflowPhase.INIT: {WorkflowPhase.PLANNING, WorkflowPhase.FAILED, WorkflowPhase.CANCELLED},
    WorkflowPhase.PLANNING: {WorkflowPhase.EXECUTING, WorkflowPhase.FAILED, WorkflowPhase.CANCELLED},
    WorkflowPhase.EXECUTING: {
        WorkflowPhase.WAITING_APPROVAL,
        WorkflowPhase.VERIFYING,
        WorkflowPhase.FAILED,
        WorkflowPhase.CANCELLED,
    },
    WorkflowPhase.WAITING_APPROVAL: {
        WorkflowPhase.EXECUTING,
        WorkflowPhase.CANCELLED,
        WorkflowPhase.FAILED,
    },
    WorkflowPhase.VERIFYING: {
        WorkflowPhase.COMPLETED,
        WorkflowPhase.EXECUTING,
        WorkflowPhase.FAILED,
    },
    WorkflowPhase.COMPLETED: set(),
    WorkflowPhase.FAILED: set(),
    WorkflowPhase.CANCELLED: set(),
}


class InvalidTransitionError(ValueError):
    pass


class OrchestrationStateMachine:
    """Simple deterministic state machine for orchestration workflows."""

    def __init__(self, state: WorkflowState):
        self.state = state

    def transition(self, next_phase: WorkflowPhase, error: str | None = None) -> None:
        current = self.state.phase
        if next_phase not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"Invalid workflow transition: {current.value} -> {next_phase.value}"
            )
        self.state.phase = next_phase
        if error:
            self.state.last_error = error
        self.state.touch()

    def fail(self, error: str) -> None:
        current = self.state.phase
        if WorkflowPhase.FAILED not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"Invalid workflow transition: {current.value} -> failed"
            )
        self.state.phase = WorkflowPhase.FAILED
        self.state.last_error = error
        self.state.touch()

    def cancel(self) -> None:
        current = self.state.phase
        if WorkflowPhase.CANCELLED not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidTransitionError(
                f"Invalid workflow transition: {current.value} -> cancelled"
            )
        self.state.phase = WorkflowPhase.CANCELLED
        self.state.touch()
