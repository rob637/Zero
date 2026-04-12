"""Campaign orchestration and prioritization for The Harness.

Consumes scenario-runner results, diagnoses failures, updates tracking, and
produces an iteration-level action plan that scales to large scenario sets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from .diagnosis import DiagnosisResult, IssueAnalyzer, RootCause

from .harness_dashboard import HarnessTracking


@dataclass
class DiagnosedFailure:
    """Normalized failure record with prioritization metadata."""

    scenario_id: str
    scenario_name: str
    category: str
    confidence: float
    remediation_priority: int
    is_remediable: bool
    issues: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    tool_names: List[str] = field(default_factory=list)
    failed_steps: int = 0
    duration_seconds: float = 0.0
    classification: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "category": self.category,
            "confidence": self.confidence,
            "remediation_priority": self.remediation_priority,
            "is_remediable": self.is_remediable,
            "issues": self.issues,
            "next_steps": self.next_steps,
            "tool_names": self.tool_names,
            "failed_steps": self.failed_steps,
            "duration_seconds": self.duration_seconds,
            "classification": self.classification,
        }


@dataclass
class CampaignIteration:
    """Iteration-level Harness intelligence summary."""

    iteration: int
    total: int
    passed: int
    failed: int
    pass_rate: float
    rerun_queue: List[str] = field(default_factory=list)
    issue_categories: Dict[str, int] = field(default_factory=dict)
    connector_hotspots: Dict[str, int] = field(default_factory=dict)
    diagnosed_failures: List[DiagnosedFailure] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "rerun_queue": self.rerun_queue,
            "issue_categories": self.issue_categories,
            "connector_hotspots": self.connector_hotspots,
            "diagnosed_failures": [failure.to_dict() for failure in self.diagnosed_failures],
        }


class ScenarioCampaignEngine:
    """Diagnoses scenario campaigns and produces rerun priorities."""

    def __init__(
        self,
        tracking: HarnessTracking | None = None,
        analyzer: IssueAnalyzer | None = None,
    ):
        self.tracking = tracking or HarnessTracking()
        self.analyzer = analyzer or IssueAnalyzer()

    def ingest_results(self, results: Sequence[Any], iteration: int = 1) -> CampaignIteration:
        """Ingest one iteration of scenario results from the runner or report JSON."""
        normalized_results = [self._normalize_result(result) for result in results]
        diagnosed_failures: List[DiagnosedFailure] = []

        for result in normalized_results:
            diagnosis = None
            issue_categories = list(result.get("issues", []))
            if not result["passed"]:
                diagnosis = self.analyzer.analyze(result)
                diagnosed_failures.append(self._to_failure(result, diagnosis))
                issue_categories = [cause.category.value for cause in diagnosis.root_causes] or issue_categories

            self.tracking.record_scenario_result(
                scenario_id=result["scenario_id"],
                scenario_name=result["name"],
                result="success" if result["passed"] else "failed",
                duration_seconds=float(result.get("duration_seconds", 0.0)),
                attempts=0,
                initial_error=self._initial_error(result),
                issue_categories=issue_categories,
                affected_connectors=self._connector_candidates(result, diagnosis),
                fixed_by_remediation=False,
            )

        passed = sum(1 for result in normalized_results if result["passed"])
        total = len(normalized_results)
        failed = total - passed
        issue_categories = dict(sorted(self.tracking.issue_patterns.items(), key=lambda item: item[1], reverse=True))
        connector_hotspots = dict(
            sorted(self.tracking.connector_failures.items(), key=lambda item: item[1], reverse=True)
        )

        iteration_summary = CampaignIteration(
            iteration=iteration,
            total=total,
            passed=passed,
            failed=failed,
            pass_rate=(passed / total) if total else 0.0,
            rerun_queue=self._build_rerun_queue(diagnosed_failures),
            issue_categories=issue_categories,
            connector_hotspots=connector_hotspots,
            diagnosed_failures=diagnosed_failures,
        )
        self.tracking.record_iteration(iteration_summary.to_dict())
        return iteration_summary

    def ingest_report_payload(self, report_payload: Dict[str, Any], iteration: int = 1) -> CampaignIteration:
        """Ingest a scenario_report.json payload."""
        return self.ingest_results(report_payload.get("results", []), iteration=iteration)

    def _normalize_result(self, result: Any) -> Dict[str, Any]:
        if isinstance(result, dict):
            scenario_id = result.get("scenario_id") or result.get("id") or "unknown"
            normalized = {
                "scenario_id": scenario_id,
                "name": result.get("name") or scenario_id,
                "passed": bool(result.get("passed", False)),
                "duration_seconds": float(result.get("duration_seconds", 0.0)),
                "approvals_used": int(result.get("approvals_used", 0)),
                "failed_steps": int(result.get("failed_steps", 0)),
                "tool_names": list(result.get("tool_names", []) or []),
                "issues": list(result.get("issues", []) or []),
                "run_data": result.get("run_data") or {"raw": result.get("raw", {})},
            }
            if "classification" not in normalized["run_data"]:
                normalized["run_data"]["classification"] = result.get("classification", "unknown")
            return normalized

        return {
            "scenario_id": getattr(result, "scenario_id"),
            "name": getattr(result, "name", getattr(result, "scenario_id")),
            "passed": bool(getattr(result, "passed", False)),
            "duration_seconds": float(getattr(result, "duration_seconds", 0.0)),
            "approvals_used": int(getattr(result, "approvals_used", 0)),
            "failed_steps": int(getattr(result, "failed_steps", 0)),
            "tool_names": list(getattr(result, "tool_names", []) or []),
            "issues": list(getattr(result, "issues", []) or []),
            "run_data": getattr(result, "run_data", {"raw": {}}),
        }

    def _to_failure(self, result: Dict[str, Any], diagnosis: DiagnosisResult) -> DiagnosedFailure:
        primary = self._primary_cause(diagnosis.root_causes)
        return DiagnosedFailure(
            scenario_id=result["scenario_id"],
            scenario_name=result["name"],
            category=primary.category.value,
            confidence=primary.confidence,
            remediation_priority=diagnosis.remediation_priority,
            is_remediable=diagnosis.is_remediable,
            issues=list(result.get("issues", [])),
            next_steps=list(diagnosis.next_steps),
            tool_names=list(result.get("tool_names", [])),
            failed_steps=int(result.get("failed_steps", 0)),
            duration_seconds=float(result.get("duration_seconds", 0.0)),
            classification=str(result.get("run_data", {}).get("classification", "unknown")),
        )

    def _primary_cause(self, root_causes: Iterable[RootCause]) -> RootCause:
        ordered = sorted(root_causes, key=lambda cause: cause.confidence, reverse=True)
        return ordered[0]

    def _build_rerun_queue(self, failures: Sequence[DiagnosedFailure]) -> List[str]:
        ordered = sorted(
            failures,
            key=lambda failure: (
                failure.remediation_priority,
                0 if failure.is_remediable else 1,
                -failure.confidence,
                -failure.failed_steps,
                -failure.duration_seconds,
                failure.scenario_id,
            ),
        )
        return [failure.scenario_id for failure in ordered]

    def _initial_error(self, result: Dict[str, Any]) -> str:
        raw = result.get("run_data", {}).get("raw", {})
        if isinstance(raw, dict) and raw.get("error"):
            return str(raw.get("error"))
        issues = result.get("issues", [])
        return str(issues[0]) if issues else ""

    def _connector_candidates(
        self,
        result: Dict[str, Any],
        diagnosis: DiagnosisResult | None,
    ) -> List[str]:
        if diagnosis and diagnosis.failed_steps:
            connectors = [str(step.get("tool", "")) for step in diagnosis.failed_steps if step.get("tool")]
            if connectors:
                return connectors
        return [tool for tool in result.get("tool_names", []) if tool]