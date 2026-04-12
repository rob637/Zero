import importlib.util
import json
from pathlib import Path
import sys

from harness.harness_dashboard import HarnessDashboard
from harness.scenario_campaign_engine import ScenarioCampaignEngine


def _load_run_scenarios_module():
    file_path = Path("/workspaces/Zero/apex/tools/run_scenarios.py")
    spec = importlib.util.spec_from_file_location("test_run_scenarios_module", file_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runner_writes_harness_report_with_rerun_queue(tmp_path):
    module = _load_run_scenarios_module()
    engine = ScenarioCampaignEngine()
    dashboard = HarnessDashboard(engine.tracking)

    results = [
        module.ScenarioResult(
            scenario_id="missing-tool",
            name="Missing Tool Scenario",
            passed=False,
            duration_seconds=5.0,
            approvals_used=0,
            failed_steps=0,
            tool_names=[],
            issues=["missing_tools: ['email_list']"],
            response_preview="",
            run_data={"classification": "configuration", "raw": {"steps": [], "is_complete": False}},
        ),
        module.ScenarioResult(
            scenario_id="passing",
            name="Passing Scenario",
            passed=True,
            duration_seconds=2.0,
            approvals_used=0,
            failed_steps=0,
            tool_names=["calendar_list"],
            issues=[],
            response_preview="ok",
            run_data={"classification": "pass", "raw": {"steps": [], "is_complete": True}},
        ),
    ]

    campaign_iteration = engine.ingest_results(results, iteration=1)
    payload = module._write_harness_report(
        tmp_path,
        dashboard,
        campaign_iteration,
        generated_at="2026-04-11T00:00:00+00:00",
    )

    json_report = json.loads((tmp_path / "harness_report.json").read_text(encoding="utf-8"))
    markdown_report = (tmp_path / "harness_report.md").read_text(encoding="utf-8")

    assert payload["campaign_iteration"]["rerun_queue"] == ["missing-tool"]
    assert json_report["campaign_iteration"]["rerun_queue"] == ["missing-tool"]
    assert "Missing Tool Scenario" in markdown_report
    assert "Rerun Queue" in markdown_report