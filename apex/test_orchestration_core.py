from pathlib import Path

from orchestration.artifact_ledger import ArtifactLedger, extract_artifact_candidates
from orchestration.contracts import OutcomeContract, WorkflowPhase, WorkflowState
from orchestration.state_machine import InvalidTransitionError, OrchestrationStateMachine


def test_state_machine_happy_path():
    state = WorkflowState(
        workflow_id="wf_1",
        session_id="sess_1",
        outcome=OutcomeContract(user_request="send report"),
    )
    sm = OrchestrationStateMachine(state)

    sm.transition(WorkflowPhase.PLANNING)
    sm.transition(WorkflowPhase.EXECUTING)
    sm.transition(WorkflowPhase.VERIFYING)
    sm.transition(WorkflowPhase.COMPLETED)

    assert state.phase == WorkflowPhase.COMPLETED


def test_state_machine_invalid_transition():
    state = WorkflowState(
        workflow_id="wf_2",
        session_id="sess_2",
        outcome=OutcomeContract(user_request="send report"),
    )
    sm = OrchestrationStateMachine(state)

    try:
        sm.transition(WorkflowPhase.COMPLETED)
        assert False, "Expected InvalidTransitionError"
    except InvalidTransitionError:
        assert True


def test_artifact_extraction_and_ledger(tmp_path: Path):
    db_path = tmp_path / "orch.db"
    ledger = ArtifactLedger(db_path)

    result = {
        "path": "/tmp/report.csv",
        "attachments": [
            "/tmp/report.csv",
            {"url": "https://example.com/doc/123"},
        ],
    }

    candidates = extract_artifact_candidates("document_create", result)
    assert len(candidates) >= 2

    for c in candidates:
        ledger.record_artifact(
            workflow_id="wf_3",
            step_id="step_1",
            tool_name="document_create",
            artifact_type=c["artifact_type"],
            uri=c["uri"],
            metadata=c.get("metadata", {}),
        )

    stored = ledger.list_artifacts("wf_3")
    assert len(stored) >= 2
