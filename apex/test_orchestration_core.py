from pathlib import Path

from orchestration.artifact_ledger import ArtifactLedger, extract_artifact_candidates
from orchestration.capability_graph import OrchestrationCapabilityGraph
from orchestration.contracts import OutcomeContract, WorkflowPhase, WorkflowState
from orchestration.evaluator import evaluate_runtime_snapshot
from orchestration.state_machine import InvalidTransitionError, OrchestrationStateMachine
from orchestration.verifier import check_side_effect_preconditions, verify_outcome


class _DummyStatus:
    def __init__(self, value: str):
        self.value = value


class _DummyStep:
    def __init__(self, status: str, requires_approval: bool = False):
        self.status = _DummyStatus(status)
        self.requires_approval = requires_approval


class _DummyState:
    def __init__(self, steps, pending_approval=None, llm_calls: int = 0):
        self.steps = steps
        self.pending_approval = pending_approval
        self.llm_calls = llm_calls


class _DummyToolCall:
    def __init__(self, name: str, params=None):
        self.name = name
        self.params = params or {}


class _DummyPendingStep:
    def __init__(self, tool_name: str, params=None):
        self.tool_call = _DummyToolCall(tool_name, params or {})


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


def test_capability_graph_summary():
    class _Tool:
        def __init__(self, name: str, side_effect: bool):
            self.name = name
            self.side_effect = side_effect

    tools = [
        _Tool("file_search", False),
        _Tool("file_read", False),
        _Tool("email_send", True),
    ]
    graph = OrchestrationCapabilityGraph.from_tools(tools)
    summary = graph.summary().to_dict()

    assert summary["total_tools"] == 3
    assert summary["side_effect_tools"] == 1
    assert summary["domains"]["FILE"] == 2
    assert summary["domains"]["EMAIL"] == 1


def test_outcome_verifier_detects_missing_artifact_and_action():
    outcome = OutcomeContract(
        user_request="create file and email",
        required_artifact_hints=["artifact_output"],
        required_side_effect_hints=["communication_send"],
    )
    state = _DummyState(steps=[_DummyStep("completed", requires_approval=False)], llm_calls=18)
    res = verify_outcome(outcome, state, artifacts=[])

    assert res.satisfied is False
    assert any("No output artifacts" in issue for issue in res.issues)
    assert any("No side-effect action" in issue for issue in res.issues)


def test_side_effect_preconditions_require_artifact_for_delivery():
    outcome = OutcomeContract(
        user_request="create report and send it",
        required_artifact_hints=["artifact_output"],
        required_side_effect_hints=["communication_send"],
    )
    pending = _DummyPendingStep("email_send", {"to": "x@example.com", "subject": "Report", "body": "Here"})

    issues = check_side_effect_preconditions(outcome, pending, artifacts=[])
    assert len(issues) == 1


def test_side_effect_preconditions_pass_with_attachment_reference():
    outcome = OutcomeContract(
        user_request="create report and send it",
        required_artifact_hints=["artifact_output"],
        required_side_effect_hints=["communication_send"],
    )
    pending = _DummyPendingStep(
        "email_send",
        {
            "to": "x@example.com",
            "subject": "Report",
            "body": "Here",
            "attachments": ["/tmp/report.csv"],
        },
    )

    issues = check_side_effect_preconditions(outcome, pending, artifacts=[])
    assert issues == []


def test_evaluator_scores_runtime_snapshot():
    verification = {"satisfied": True, "score": 0.9}
    ev = evaluate_runtime_snapshot(
        llm_calls=6,
        tool_calls=14,
        wall_time_ms=12000,
        verification=verification,
    )
    d = ev.to_dict()

    assert d["score"] >= 0.7
    assert d["success"] is True
    assert 0.0 <= d["efficiency"] <= 1.0
