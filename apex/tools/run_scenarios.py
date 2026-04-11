#!/usr/bin/env python3
"""Run prompt scenarios against Telic chat endpoints and evaluate outcomes.

Usage:
  python apex/tools/run_scenarios.py --base-url http://127.0.0.1:8000 \
      --scenario-file apex/scenarios/regression_scenarios.json --auto-approve
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx


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


def _load_scenarios(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


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
        (r"not configured|api key|connect .* key", "configuration"),
        (r"403|404|429|getaddrinfo|dns|forbidden|not found", "external_dependency"),
        (r"timed out|timeout|maximum number of steps|not making enough progress", "orchestration"),
        (r"ssl|wrong_version_number|certificate", "transport_ssl"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return "unknown"


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
    if isinstance(max_failed_steps, int) and failed_steps > max_failed_steps:
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

    payload = _post_json(
        client,
        f"{base_url}/react/chat",
        {
            "message": scenario["prompt"],
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

    json_payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [
            {
                "id": r.scenario_id,
                "name": r.name,
                "passed": r.passed,
                "duration_seconds": round(r.duration_seconds, 3),
                "approvals_used": r.approvals_used,
                "failed_steps": r.failed_steps,
                "tool_names": r.tool_names,
                "issues": r.issues,
                "response_preview": r.response_preview,
                "run_data": r.run_data,
            }
            for r in results
        ],
    }

    (out_dir / "scenario_report.json").write_text(json.dumps(json_payload, indent=2), encoding="utf-8")

    lines = [
        "# Scenario Report",
        "",
        f"Total: {json_payload['total']}  ",
        f"Passed: {json_payload['passed']}  ",
        f"Failed: {json_payload['failed']}",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Telic prompt scenarios and evaluate results.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Telic API base URL")
    parser.add_argument("--scenario-file", default="apex/scenarios/regression_scenarios.json", help="Scenario spec JSON file")
    parser.add_argument("--scenario", action="append", default=[], help="Scenario ID to run (repeatable)")
    parser.add_argument("--auto-approve", action="store_true", help="Automatically approve pending actions")
    parser.add_argument("--out-dir", default="apex/scenarios/reports/latest", help="Output report directory")
    parser.add_argument("--allow-failures", action="store_true", help="Always exit 0 even on scenario failures")
    args = parser.parse_args()

    spec = _load_scenarios(Path(args.scenario_file))
    defaults = spec.get("defaults", {}) if isinstance(spec, dict) else {}
    scenarios = spec.get("scenarios", []) if isinstance(spec, dict) else []
    if not scenarios:
        print("No scenarios found.", file=sys.stderr)
        return 2

    selected_ids = set(args.scenario)
    if selected_ids:
        scenarios = [s for s in scenarios if s.get("id") in selected_ids]
        if not scenarios:
            print(f"No matching scenarios for ids={sorted(selected_ids)}", file=sys.stderr)
            return 2

    results: List[ScenarioResult] = []

    with httpx.Client(follow_redirects=True) as client:
        for scenario in scenarios:
            sid = scenario.get("id", "?")
            name = scenario.get("name", sid)
            print(f"[RUN] {sid}: {name}")
            try:
                result = _run_scenario(
                    client=client,
                    base_url=args.base_url.rstrip("/"),
                    scenario=scenario,
                    defaults=defaults,
                    auto_approve=args.auto_approve,
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

    _write_report(Path(args.out_dir), results)
    failed = [r for r in results if not r.passed]
    print(f"Wrote report to {args.out_dir}")

    if failed and not args.allow_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
