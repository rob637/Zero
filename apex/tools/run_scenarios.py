#!/usr/bin/env python3
"""Run prompt scenarios against Telic chat endpoints and evaluate outcomes.

Usage:
  python apex/tools/run_scenarios.py --base-url http://127.0.0.1:8000 \
      --scenario-file apex/scenarios/regression_scenarios.json --auto-approve
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from harness.harness_dashboard import HarnessDashboard
from harness.scenario_campaign_engine import CampaignIteration, ScenarioCampaignEngine


@dataclass
class ScenarioResult:
    scenario_id: str
    name: str
    passed: bool
    duration_seconds: float
    approvals_used: int
    failed_steps: int
    tool_names: List[str]
    issues: List[str]
    response_preview: str
    run_data: Dict[str, Any]


@dataclass
class IterationSummary:
    iteration: int
    total: int
    passed: int
    failed: int
    pass_rate: float
    effective_total: int
    effective_passed: int
    effective_pass_rate: float
    configuration_blocked: int
    failed_ids: List[str]
    top_failure_signatures: List[Tuple[str, int]]


def _scenario_result_to_dict(result: ScenarioResult) -> Dict[str, Any]:
    return {
        "id": result.scenario_id,
        "name": result.name,
        "passed": result.passed,
        "duration_seconds": round(result.duration_seconds, 3),
        "approvals_used": result.approvals_used,
        "failed_steps": result.failed_steps,
        "tool_names": result.tool_names,
        "issues": result.issues,
        "response_preview": result.response_preview,
        "run_data": result.run_data,
    }


def _load_scenarios(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_scenarios_from_dir(path: Path, glob: str) -> Dict[str, Any]:
    files = sorted(path.glob(glob))
    if not files:
        return {"defaults": {}, "scenarios": []}

    merged_defaults: Dict[str, Any] = {}
    merged_scenarios: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    for file_path in files:
        payload = _load_scenarios(file_path)
        defaults = payload.get("defaults", {}) if isinstance(payload, dict) else {}
        scenarios = payload.get("scenarios", []) if isinstance(payload, dict) else []
        if defaults and not merged_defaults:
            merged_defaults = defaults

        for scenario in scenarios:
            sid = scenario.get("id")
            if not sid:
                continue
            if sid in seen_ids:
                raise ValueError(f"Duplicate scenario id across files: {sid}")
            seen_ids.add(sid)
            merged_scenarios.append(scenario)

    return {"defaults": merged_defaults, "scenarios": merged_scenarios}


def _match_any(patterns: List[str], text: str) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
            return True
    return False


def _collect_text_from_steps(steps: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for step in steps:
        err = step.get("error")
        if err:
            parts.append(str(err))
        result = step.get("result")
        if isinstance(result, str):
            parts.append(result)
        elif isinstance(result, dict):
            parts.append(json.dumps(result, default=str))
    return "\n".join(parts)


def _classify_issue(issues: List[str], run_payload: Dict[str, Any]) -> str:
    text = "\n".join(issues + [json.dumps(run_payload, default=str)])
    patterns = [
        (r"configuration_blocked", "configuration_blocked"),
        (r"not configured|api key|connect .* key", "configuration"),
        (r"403|404|429|getaddrinfo|dns|forbidden|not found", "external_dependency"),
        (r"timed out|timeout|maximum number of steps|not making enough progress", "orchestration"),
        (r"ssl|wrong_version_number|certificate", "transport_ssl"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return "unknown"


def _is_configuration_blocked(
    *,
    required_tools: List[str],
    missing_tools: List[str],
    steps: List[Dict[str, Any]],
) -> bool:
    if missing_tools:
        return True

    required = {tool for tool in required_tools}
    if not required:
        return False

    failed_required_steps = [
        step for step in steps
        if step.get("status") == "failed" and str(step.get("tool", "")) in required
    ]
    if not failed_required_steps:
        return False

    availability_markers = (
        "not available",
        "not connected",
        "unknown tool",
        "tool unavailable",
        "insufficientpermissions",
        "insufficient permission",
        "forbidden",
        "requires authentication",
        "connector returned not connected",
        "missing credential",
        "not configured",
    )

    for step in failed_required_steps:
        step_text = "\n".join(
            [
                str(step.get("error") or ""),
                json.dumps(step.get("result"), default=str),
            ]
        ).lower()
        if any(marker in step_text for marker in availability_markers):
            return True
    return False


def _summarize_outcomes(results: List[ScenarioResult]) -> Dict[str, Any]:
    total = len(results)
    passed = sum(1 for result in results if result.passed)
    failed = total - passed
    strict_pass_rate = (passed / total) if total else 0.0

    configuration_blocked = sum(
        1
        for result in results
        if str(result.run_data.get("classification", "")) == "configuration_blocked"
    )
    effective_total = max(0, total - configuration_blocked)
    effective_passed = passed
    effective_pass_rate = (effective_passed / effective_total) if effective_total else 1.0

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "strict_pass_rate": strict_pass_rate,
        "effective_total": effective_total,
        "effective_passed": effective_passed,
        "effective_pass_rate": effective_pass_rate,
        "configuration_blocked": configuration_blocked,
    }


def _evaluate(
    scenario: Dict[str, Any],
    payload: Dict[str, Any],
    duration_seconds: float,
    approvals_used: int,
) -> ScenarioResult:
    checks = scenario.get("checks", {})
    steps: List[Dict[str, Any]] = payload.get("steps", []) or []
    response_text = payload.get("response") or ""

    tool_names = [str(step.get("tool", "")) for step in steps if step.get("tool")]
    failed_steps = sum(1 for step in steps if step.get("status") == "failed")

    issues: List[str] = []

    required_tools = checks.get("required_tools", []) or []
    missing_tools = [t for t in required_tools if t not in tool_names]
    if missing_tools:
        issues.append(f"missing_tools: {missing_tools}")

    configuration_blocked = _is_configuration_blocked(
        required_tools=required_tools,
        missing_tools=missing_tools,
        steps=steps,
    )
    if configuration_blocked:
        issues.append("configuration_blocked: required tools unavailable or unhealthy in current environment")

    forbidden_tools = checks.get("forbidden_tools", []) or []
    used_forbidden = [t for t in tool_names if t in forbidden_tools]
    if used_forbidden:
        issues.append(f"forbidden_tools_used: {sorted(set(used_forbidden))}")

    required_output_patterns = checks.get("required_output_patterns", []) or []
    for pattern in required_output_patterns:
        if not re.search(pattern, response_text, flags=re.IGNORECASE | re.MULTILINE):
            issues.append(f"missing_output_pattern: {pattern}")

    forbidden_output_patterns = checks.get("forbidden_output_patterns", []) or []
    for pattern in forbidden_output_patterns:
        if re.search(pattern, response_text, flags=re.IGNORECASE | re.MULTILINE):
            issues.append(f"forbidden_output_pattern: {pattern}")

    max_failed_steps = checks.get("max_failed_steps")
    if isinstance(max_failed_steps, int) and failed_steps > max_failed_steps and not configuration_blocked:
        issues.append(f"failed_steps_exceeded: {failed_steps} > {max_failed_steps}")

    step_text = _collect_text_from_steps(steps)
    forbidden_error_patterns = checks.get("forbidden_error_patterns", []) or []
    for pattern in forbidden_error_patterns:
        if re.search(pattern, step_text, flags=re.IGNORECASE | re.MULTILINE):
            issues.append(f"forbidden_error_pattern: {pattern}")

    if payload.get("pending_approval"):
        issues.append("pending_approval_not_resolved")

    if not payload.get("is_complete", False):
        issues.append("scenario_not_complete")

    passed = len(issues) == 0
    run_data = {
        "classification": _classify_issue(issues, payload) if issues else "pass",
        "usage": payload.get("usage"),
        "meta": payload.get("meta"),
        "raw": payload,
    }

    return ScenarioResult(
        scenario_id=scenario["id"],
        name=scenario.get("name", scenario["id"]),
        passed=passed,
        duration_seconds=duration_seconds,
        approvals_used=approvals_used,
        failed_steps=failed_steps,
        tool_names=sorted(set(tool_names)),
        issues=issues,
        response_preview=(response_text[:600] + "...") if len(response_text) > 600 else response_text,
        run_data=run_data,
    )


def _post_json(client: httpx.Client, url: str, payload: Dict[str, Any], timeout_s: float) -> Dict[str, Any]:
    r = client.post(url, json=payload, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"Unexpected response type from {url}: {type(data)}")
    return data


def _preflight(client: httpx.Client, base_url: str, timeout_s: float = 20.0) -> Optional[str]:
    """Return a configuration blocker message if runtime is not scenario-testable."""
    try:
        payload = _post_json(
            client,
            f"{base_url}/react/chat",
            {
                "message": "healthcheck",
                "session_id": f"preflight-{uuid.uuid4().hex[:8]}",
                "orchestration_mode": "fast",
            },
            timeout_s,
        )
    except Exception as e:
        return f"preflight_request_failed: {e}"

    response = str(payload.get("response") or "")
    error = str(payload.get("error") or "")
    text = "\n".join([response, error]).lower()
    blockers = [
        "incorrect api key",
        "invalid_api_key",
        "no api key configured",
        "authentication_error",
        "failed to authenticate",
        "invalid x-api-key",
        "deployment could not be found on vercel",
        "telic-proxy",
    ]
    for marker in blockers:
        if marker in text:
            prefix = "proxy_configuration_blocker" if "proxy" in marker or "vercel" in marker else "llm_configuration_blocker"
            return f"{prefix}: {marker}"
    return None


def _run_scenario(
    client: httpx.Client,
    base_url: str,
    scenario: Dict[str, Any],
    defaults: Dict[str, Any],
    auto_approve: bool,
) -> ScenarioResult:
    timeout_s = float(scenario.get("timeout_seconds", defaults.get("timeout_seconds", 180)))
    orchestration_mode = scenario.get("orchestration_mode", defaults.get("orchestration_mode", "balanced"))
    max_approvals = int(scenario.get("max_approvals", defaults.get("max_approvals", 8)))

    session_id = f"scn-{scenario['id']}-{uuid.uuid4().hex[:8]}"
    t0 = time.perf_counter()

    checks = scenario.get("checks", {}) if isinstance(scenario, dict) else {}
    required_tools = checks.get("required_tools", []) or []
    required_output_patterns = checks.get("required_output_patterns", []) or []
    forbidden_error_patterns = checks.get("forbidden_error_patterns", []) or []
    contract_lines = [
        scenario["prompt"],
        "",
        "Scenario execution contract:",
        "- Prefer calling required tools at least once when they are available in this environment.",
        "- If a required tool is unavailable, state that explicitly in the final response.",
        "- Produce a complete answer that satisfies the output requirements.",
    ]
    if required_tools:
        contract_lines.append(f"- Required tools: {', '.join(map(str, required_tools))}")
    if required_output_patterns:
        contract_lines.append(f"- Required output signals: {', '.join(map(str, required_output_patterns))}")
    if forbidden_error_patterns:
        contract_lines.append(f"- Avoid these failure/error signatures: {', '.join(map(str, forbidden_error_patterns))}")
    scenario_message = "\n".join(contract_lines)

    payload = _post_json(
        client,
        f"{base_url}/react/chat",
        {
            "message": scenario_message,
            "session_id": session_id,
            "orchestration_mode": orchestration_mode,
        },
        timeout_s,
    )

    approvals_used = 0
    while payload.get("pending_approval") and approvals_used < max_approvals:
        if not auto_approve:
            break
        payload = _post_json(
            client,
            f"{base_url}/react/approve",
            {
                "approved": True,
                "session_id": session_id,
                "orchestration_mode": orchestration_mode,
            },
            timeout_s,
        )
        approvals_used += 1

    dt = time.perf_counter() - t0
    result = _evaluate(scenario, payload, dt, approvals_used)
    return result


def _write_report(out_dir: Path, results: List[ScenarioResult]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = _summarize_outcomes(results)

    json_payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": summary["total"],
        "passed": summary["passed"],
        "failed": summary["failed"],
        "strict_pass_rate": round(float(summary["strict_pass_rate"]), 4),
        "effective_total": summary["effective_total"],
        "effective_passed": summary["effective_passed"],
        "effective_pass_rate": round(float(summary["effective_pass_rate"]), 4),
        "configuration_blocked": summary["configuration_blocked"],
        "results": [_scenario_result_to_dict(r) for r in results],
    }

    (out_dir / "scenario_report.json").write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    lines = [
        "# Scenario Report",
        "",
        f"Total: {json_payload['total']}  ",
        f"Passed: {json_payload['passed']}  ",
        f"Failed: {json_payload['failed']}",
        f"Strict Pass Rate: {json_payload['strict_pass_rate']:.2%}  ",
        (
            "Effective Pass Rate (excluding configuration-blocked scenarios): "
            f"{json_payload['effective_pass_rate']:.2%} "
            f"[{json_payload['effective_passed']}/{json_payload['effective_total']}]"
        ),
        f"Configuration-Blocked: {json_payload['configuration_blocked']}",
        "",
        "| ID | Name | Status | Duration(s) | Failed Steps | Classification |",
        "|---|---|---|---:|---:|---|",
    ]
    for r in results:
        classification = r.run_data.get("classification", "")
        status = "PASS" if r.passed else "FAIL"
        lines.append(
            f"| {r.scenario_id} | {r.name} | {status} | {r.duration_seconds:.2f} | {r.failed_steps} | {classification} |"
        )

    lines.append("")
    lines.append("## Failures")
    lines.append("")
    failed = [r for r in results if not r.passed]
    if not failed:
        lines.append("No failures.")
    else:
        for r in failed:
            lines.append(f"### {r.scenario_id} - {r.name}")
            lines.append("")
            for issue in r.issues:
                lines.append(f"- {issue}")
            lines.append("")

    (out_dir / "scenario_report.md").write_text("\n".join(lines), encoding="utf-8")


def _failure_signatures(results: List[ScenarioResult]) -> Counter:
    signatures: Counter = Counter()
    for r in results:
        if r.passed:
            continue
        if r.issues:
            for issue in r.issues:
                signatures[issue] += 1
        else:
            signatures["unknown_failure"] += 1
    return signatures


def _summarize_iteration(iteration: int, results: List[ScenarioResult]) -> IterationSummary:
    summary = _summarize_outcomes(results)
    failed_ids = [r.scenario_id for r in results if not r.passed]
    top_failure_signatures = _failure_signatures(results).most_common(12)
    return IterationSummary(
        iteration=iteration,
        total=summary["total"],
        passed=summary["passed"],
        failed=summary["failed"],
        pass_rate=float(summary["strict_pass_rate"]),
        effective_total=summary["effective_total"],
        effective_passed=summary["effective_passed"],
        effective_pass_rate=float(summary["effective_pass_rate"]),
        configuration_blocked=summary["configuration_blocked"],
        failed_ids=failed_ids,
        top_failure_signatures=top_failure_signatures,
    )


def _write_campaign_report(out_dir: Path, campaign: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "campaign_report.json").write_text(json.dumps(campaign, indent=2), encoding="utf-8")

    lines = [
        "# Scenario Campaign Report",
        "",
        f"Generated: {campaign.get('generated_at', '')}",
        f"Iterations Executed: {campaign.get('iterations_executed', 0)}",
        f"Target Pass Rate: {campaign.get('target_pass_rate', 1.0):.2%}",
        f"Final Pass Rate: {campaign.get('final_pass_rate', 0.0):.2%}",
        f"Final Effective Pass Rate: {campaign.get('final_effective_pass_rate', 0.0):.2%}",
        f"Configuration-Blocked Scenarios: {campaign.get('configuration_blocked', 0)}",
        f"Converged: {'yes' if campaign.get('converged') else 'no'}",
        "",
        "## Iteration Trend",
        "",
        "| Iteration | Total | Passed | Failed | Pass Rate | Effective Pass | Config Blocked | Top Failure Signatures |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]

    for it in campaign.get("iterations", []):
        top = ", ".join(f"{name} ({count})" for name, count in it.get("top_failure_signatures", [])[:3])
        lines.append(
            f"| {it.get('iteration')} | {it.get('total')} | {it.get('passed')} | {it.get('failed')} "
            f"| {it.get('pass_rate', 0.0):.2%} | {it.get('effective_pass_rate', 0.0):.2%} | {it.get('configuration_blocked', 0)} | {top or '-'} |"
        )

    lines.append("")
    lines.append("## Final Failed Scenarios")
    lines.append("")
    failed_ids = campaign.get("final_failed_ids", [])
    if not failed_ids:
        lines.append("None")
    else:
        for sid in failed_ids:
            lines.append(f"- {sid}")

    (out_dir / "campaign_report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_harness_report(
    out_dir: Path,
    dashboard: HarnessDashboard,
    campaign_iteration: CampaignIteration,
    *,
    generated_at: str,
) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    health = dashboard.render_health_check()
    export = dashboard.export_json()
    harness_payload = {
        "generated_at": generated_at,
        "summary": export.get("global_stats", {}),
        "health": health,
        "campaign_iteration": campaign_iteration.to_dict(),
        "scenarios": export.get("scenarios", []),
        "iterations": export.get("iterations", []),
    }
    (out_dir / "harness_report.json").write_text(json.dumps(harness_payload, indent=2), encoding="utf-8")

    lines = [
        "# Harness Report",
        "",
        f"Generated: {generated_at}",
        "",
        "## Dashboard",
        "",
        "```text",
        dashboard.render_summary().strip("\n"),
        dashboard.render_table().strip("\n"),
        "```",
        "",
        "## Health",
        "",
        f"Critical: {len(health.get('critical', []))}",
        f"Warning: {len(health.get('warning', []))}",
        f"Healthy: {len(health.get('healthy', []))}",
        "",
        "## Rerun Queue",
        "",
    ]

    if campaign_iteration.rerun_queue:
        for scenario_id in campaign_iteration.rerun_queue:
            lines.append(f"- {scenario_id}")
    else:
        lines.append("No reruns queued.")

    lines.extend([
        "",
        "## Diagnosed Failures",
        "",
    ])

    if campaign_iteration.diagnosed_failures:
        for failure in campaign_iteration.diagnosed_failures:
            lines.append(f"### {failure.scenario_id} - {failure.scenario_name}")
            lines.append("")
            lines.append(f"- Category: {failure.category}")
            lines.append(f"- Priority: {failure.remediation_priority}")
            lines.append(f"- Remediable: {'yes' if failure.is_remediable else 'no'}")
            lines.append(f"- Confidence: {failure.confidence:.0%}")
            if failure.issues:
                lines.append(f"- Issues: {', '.join(failure.issues[:3])}")
            if failure.next_steps:
                lines.append(f"- Next steps: {' | '.join(failure.next_steps[:3])}")
            lines.append("")
    else:
        lines.append("No diagnosed failures.")

    (out_dir / "harness_report.md").write_text("\n".join(lines), encoding="utf-8")
    return harness_payload


def _run_iteration(
    client: httpx.Client,
    base_url: str,
    scenarios: List[Dict[str, Any]],
    defaults: Dict[str, Any],
    auto_approve: bool,
) -> List[ScenarioResult]:
    results: List[ScenarioResult] = []
    for scenario in scenarios:
        sid = scenario.get("id", "?")
        name = scenario.get("name", sid)
        print(f"[RUN] {sid}: {name}")
        try:
            result = _run_scenario(
                client=client,
                base_url=base_url,
                scenario=scenario,
                defaults=defaults,
                auto_approve=auto_approve,
            )
        except Exception as e:
            result = ScenarioResult(
                scenario_id=sid,
                name=name,
                passed=False,
                duration_seconds=0.0,
                approvals_used=0,
                failed_steps=0,
                tool_names=[],
                issues=[f"runner_exception: {e}"],
                response_preview="",
                run_data={"classification": "runner", "raw": {}},
            )
        results.append(result)
        print(f"[{'PASS' if result.passed else 'FAIL'}] {sid} ({result.duration_seconds:.1f}s)")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Telic prompt scenarios and evaluate results.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Telic API base URL")
    parser.add_argument("--scenario-file", default="apex/scenarios/regression_scenarios.json", help="Scenario spec JSON file")
    parser.add_argument("--scenario-dir", default="", help="Directory with scenario JSON files to merge")
    parser.add_argument("--scenario-glob", default="*.json", help="Glob used with --scenario-dir")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario ID to run (repeatable)")
    parser.add_argument(
        "--suite",
        default="all",
        choices=["all", "core", "nightly"],
        help="Run scenarios in a named suite (all/core/nightly)",
    )
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve pending actions")
    parser.add_argument("--out-dir", default="apex/scenarios/reports/latest", help="Output report directory")
    parser.add_argument("--allow-failures", action="store_true", help="Always exit 0 even on scenario failures")
    parser.add_argument("--iterations", type=int, default=1, help="Run iterative campaign for N iterations")
    parser.add_argument(
        "--target-pass-rate",
        type=float,
        default=1.0,
        help="Stop when pass rate reaches this threshold (0.0-1.0)",
    )
    parser.add_argument(
        "--max-no-improvement",
        type=int,
        default=2,
        help="Stop after this many non-improving iterations",
    )
    parser.add_argument(
        "--rerun-failed-only",
        action="store_true",
        help="After the first iteration, run only failed scenarios to accelerate triage",
    )
    parser.add_argument("--scenario-limit", type=int, default=0, help="Cap number of loaded scenarios (0 = all)")
    parser.add_argument("--shard-index", type=int, default=0, help="0-based shard index for distributed runs")
    parser.add_argument("--shard-total", type=int, default=1, help="Total shard count for distributed runs")
    parser.add_argument("--shuffle", action="store_true", help="Shuffle scenario execution order")
    parser.add_argument("--seed", type=int, default=42, help="Random seed used when --shuffle is enabled")
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip runtime preflight checks (not recommended)",
    )
    args = parser.parse_args()

    if args.scenario_dir:
        spec = _load_scenarios_from_dir(Path(args.scenario_dir), args.scenario_glob)
    else:
        spec = _load_scenarios(Path(args.scenario_file))
    defaults = spec.get("defaults", {}) if isinstance(spec, dict) else {}
    scenarios = spec.get("scenarios", []) if isinstance(spec, dict) else []
    if not scenarios:
        print("No scenarios found.", file=sys.stderr)
        return 2

    if args.suite != "all":
        selected_suite = args.suite
        scenarios = [
            s for s in scenarios
            if selected_suite in (s.get("suites") or [])
        ]
        if not scenarios:
            print(f"No scenarios found for suite='{selected_suite}'", file=sys.stderr)
            return 2

    selected_ids = set(args.scenario)
    if selected_ids:
        scenarios = [s for s in scenarios if s.get("id") in selected_ids]
        if not scenarios:
            print(f"No matching scenarios for ids={sorted(selected_ids)}", file=sys.stderr)
            return 2

    shard_total = max(1, int(args.shard_total))
    shard_index = int(args.shard_index)
    if shard_index < 0 or shard_index >= shard_total:
        print(f"Invalid shard settings: shard_index={shard_index}, shard_total={shard_total}", file=sys.stderr)
        return 2
    if shard_total > 1:
        scenarios = [s for i, s in enumerate(scenarios) if i % shard_total == shard_index]

    if args.shuffle:
        rng = random.Random(args.seed)
        rng.shuffle(scenarios)

    if args.scenario_limit and args.scenario_limit > 0:
        scenarios = scenarios[: args.scenario_limit]

    if not scenarios:
        print("No scenarios selected after filters.", file=sys.stderr)
        return 2

    target_pass_rate = max(0.0, min(1.0, float(args.target_pass_rate)))
    max_iterations = max(1, int(args.iterations))
    max_no_improvement = max(0, int(args.max_no_improvement))

    iterations_payload: List[Dict[str, Any]] = []
    best_pass_rate = -1.0
    stagnant_iters = 0
    final_results: List[ScenarioResult] = []
    current_scenarios = list(scenarios)
    scenario_by_id = {s.get("id"): s for s in scenarios}
    harness_engine = ScenarioCampaignEngine()
    harness_dashboard = HarnessDashboard(harness_engine.tracking)
    latest_campaign_iteration: Optional[CampaignIteration] = None
    latest_generated_at: Optional[str] = None

    with httpx.Client(follow_redirects=True) as client:
        if not args.skip_preflight:
            blocker = _preflight(client, args.base_url.rstrip("/"))
            if blocker:
                print(f"[BLOCKED] {blocker}", file=sys.stderr)
                return 0 if args.allow_failures else 3

        for iteration in range(1, max_iterations + 1):
            print(f"[ITERATION] {iteration}/{max_iterations} scenarios={len(current_scenarios)}")
            run_results = _run_iteration(
                client=client,
                base_url=args.base_url.rstrip("/"),
                scenarios=current_scenarios,
                defaults=defaults,
                auto_approve=args.auto_approve,
            )
            final_results = run_results

            iter_dir = Path(args.out_dir) / "iterations" / f"iter-{iteration:03d}"
            _write_report(iter_dir, run_results)

            campaign_iteration = harness_engine.ingest_results(run_results, iteration=iteration)
            generated_at = datetime.now(timezone.utc).isoformat()
            _write_harness_report(
                iter_dir,
                harness_dashboard,
                campaign_iteration,
                generated_at=generated_at,
            )
            latest_campaign_iteration = campaign_iteration
            latest_generated_at = generated_at

            summary = _summarize_iteration(iteration, run_results)
            iterations_payload.append(
                {
                    "iteration": summary.iteration,
                    "total": summary.total,
                    "passed": summary.passed,
                    "failed": summary.failed,
                    "pass_rate": round(summary.pass_rate, 4),
                    "effective_total": summary.effective_total,
                    "effective_passed": summary.effective_passed,
                    "effective_pass_rate": round(summary.effective_pass_rate, 4),
                    "configuration_blocked": summary.configuration_blocked,
                    "failed_ids": summary.failed_ids,
                    "top_failure_signatures": summary.top_failure_signatures,
                    "rerun_queue": campaign_iteration.rerun_queue,
                    "diagnosed_failures": [failure.to_dict() for failure in campaign_iteration.diagnosed_failures],
                }
            )

            print(
                f"[ITERATION_RESULT] pass_rate={summary.pass_rate:.2%} "
                f"passed={summary.passed}/{summary.total} failed={summary.failed}"
            )
            if campaign_iteration.rerun_queue:
                print(f"[HARNESS] prioritized reruns={','.join(campaign_iteration.rerun_queue[:5])}")

            if summary.pass_rate >= target_pass_rate:
                break

            if summary.pass_rate > best_pass_rate:
                best_pass_rate = summary.pass_rate
                stagnant_iters = 0
            else:
                stagnant_iters += 1
                if stagnant_iters > max_no_improvement:
                    print(
                        f"[STOP] no improvement for {stagnant_iters} iterations "
                        f"(max_no_improvement={max_no_improvement})"
                    )
                    break

            if args.rerun_failed_only:
                prioritized_ids = campaign_iteration.rerun_queue
                if not prioritized_ids:
                    break
                current_scenarios = [scenario_by_id[sid] for sid in prioritized_ids if sid in scenario_by_id]
                if not current_scenarios:
                    break

    _write_report(Path(args.out_dir), final_results)

    final_generated_at = latest_generated_at or datetime.now(timezone.utc).isoformat()
    final_campaign_iteration = latest_campaign_iteration or CampaignIteration(
        iteration=0,
        total=0,
        passed=0,
        failed=0,
        pass_rate=0.0,
    )
    final_harness_payload = _write_harness_report(
        Path(args.out_dir),
        harness_dashboard,
        final_campaign_iteration,
        generated_at=final_generated_at,
    )

    final_failed = [r for r in final_results if not r.passed]
    final_summary = _summarize_outcomes(final_results)
    final_pass_rate = float(final_summary["strict_pass_rate"])
    final_effective_pass_rate = float(final_summary["effective_pass_rate"])
    campaign_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "iterations_executed": len(iterations_payload),
        "target_pass_rate": target_pass_rate,
        "final_pass_rate": round(final_pass_rate, 4),
        "final_effective_pass_rate": round(final_effective_pass_rate, 4),
        "configuration_blocked": int(final_summary["configuration_blocked"]),
        "converged": final_pass_rate >= target_pass_rate and len(final_failed) == 0,
        "iterations": iterations_payload,
        "final_failed_ids": [r.scenario_id for r in final_failed],
        "final_rerun_queue": final_harness_payload.get("campaign_iteration", {}).get("rerun_queue", []),
        "summary": final_harness_payload.get("summary", {}),
    }
    _write_campaign_report(Path(args.out_dir), campaign_payload)

    print(f"Wrote report to {args.out_dir}")

    if final_failed and not args.allow_failures:
        return 1
    if final_pass_rate < target_pass_rate and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
