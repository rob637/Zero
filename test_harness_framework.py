from harness.harness_dashboard import HarnessTracking
from harness.diagnosis import IssueCategory
from harness.scenario_campaign_engine import ScenarioCampaignEngine
from harness.scenario_remediation_engine import RemediationEngine
from harness.scenario_retry_engine import ScenarioRetryEngine


def test_remediation_engine_escalates_orchestration_mode():
    engine = RemediationEngine()

    strategy = engine.get_remediation(
        category=IssueCategory.WRONG_MODE,
        root_cause="wrong_mode",
        context={"orchestration_mode": "fast"},
        error_details=["high_step_count"],
    )
    applied, updated = engine.apply_fix(strategy, {"orchestration_mode": "fast"})

    assert applied is True
    assert updated["orchestration_mode"] == "balanced"
    assert updated["last_remediation"] == "adjust_orchestration_mode"


def test_retry_engine_recovers_after_generic_mode_adjustment():
    engine = ScenarioRetryEngine(max_retries=2)

    def executor(context):
        if context.get("orchestration_mode") == "balanced":
            return True, {
                "steps": [{"tool": "calendar_list", "status": "completed"}],
                "response": "schedule created",
                "is_complete": True,
            }, ""

        return False, {
            "steps": [{"tool": "calendar_list", "status": "failed", "error": "maximum number of steps"}] * 32,
            "response": "",
            "error": "maximum number of steps",
            "is_complete": False,
        }, "maximum number of steps"

    session = engine.execute_with_retry(
        scenario_id="morning-command-center",
        scenario_name="Morning Command Center",
        scenario_executor=executor,
        context={"orchestration_mode": "fast", "timeout_seconds": 180},
    )

    assert session.final_result == "success"
    assert len(session.attempts) == 1
    assert session.attempts[0].remediation_applied == "adjust_orchestration_mode"


def test_tracking_updates_average_duration_and_issue_patterns():
    tracking = HarnessTracking()

    tracking.record_scenario_result(
        scenario_id="s1",
        scenario_name="Scenario One",
        result="failed",
        duration_seconds=10.0,
        attempts=2,
        initial_error="timeout",
        issue_categories=["timeout", "timeout"],
        affected_connectors=["calendar_list"],
    )
    tracking.record_scenario_result(
        scenario_id="s1",
        scenario_name="Scenario One",
        result="success",
        duration_seconds=20.0,
        issue_categories=["timeout"],
        fixed_by_remediation=True,
    )

    stats = tracking.get_scenario_stats("s1")
    global_stats = tracking.get_global_stats()

    assert stats.avg_duration_seconds == 15.0
    assert stats.most_common_issue == "timeout"
    assert global_stats.remediation_success_rate == 1.0
    assert global_stats.avg_retries_per_failure == 2.0


def test_campaign_engine_prioritizes_critical_failures_first():
    engine = ScenarioCampaignEngine()

    report_results = [
        {
            "id": "missing-tool",
            "name": "Missing Tool Scenario",
            "passed": False,
            "duration_seconds": 5.0,
            "approvals_used": 0,
            "failed_steps": 0,
            "tool_names": [],
            "issues": ["missing_tools: ['email_list']"],
            "run_data": {"classification": "configuration", "raw": {"steps": [], "is_complete": False}},
        },
        {
            "id": "too-many-steps",
            "name": "Too Many Steps Scenario",
            "passed": False,
            "duration_seconds": 12.0,
            "approvals_used": 0,
            "failed_steps": 5,
            "tool_names": ["calendar_list"],
            "issues": ["failed_steps_exceeded: 5 > 0"],
            "run_data": {
                "classification": "orchestration",
                "raw": {
                    "steps": [{"tool": "calendar_list", "status": "failed", "error": "maximum number of steps"}] * 32,
                    "error": "maximum number of steps",
                    "orchestration_mode": "fast",
                    "is_complete": False,
                },
            },
        },
        {
            "id": "passing",
            "name": "Passing Scenario",
            "passed": True,
            "duration_seconds": 4.0,
            "approvals_used": 0,
            "failed_steps": 0,
            "tool_names": ["calendar_list"],
            "issues": [],
            "run_data": {"classification": "pass", "raw": {"steps": [], "is_complete": True}},
        },
    ]

    iteration = engine.ingest_results(report_results, iteration=3)

    assert iteration.total == 3
    assert iteration.failed == 2
    assert iteration.rerun_queue[0] == "missing-tool"
    assert "missing_tool" in iteration.issue_categories
    assert engine.tracking.iteration_history[-1]["iteration"] == 3