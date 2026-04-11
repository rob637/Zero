"""Orchestration quality and benchmark routes."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from orchestration import (
    BenchmarkCase,
    OrchestrationEvalStore,
    QualityGateThresholds,
    audit_primitives,
    default_benchmark_cases,
    run_benchmarks,
)
import server_state as ss

router = APIRouter(prefix="/orchestration", tags=["orchestration"])
_eval_store = OrchestrationEvalStore(Path(__file__).resolve().parent.parent / "sqlite" / "orchestration.db")


class BenchmarkCaseRequest(BaseModel):
    name: str
    llm_calls: int
    tool_calls: int
    wall_time_ms: float
    verification: Dict[str, Any] = {}


class BenchmarkRunRequest(BaseModel):
    cases: Optional[List[BenchmarkCaseRequest]] = None
    thresholds: Optional[Dict[str, float]] = None


class ReplayRunRequest(BaseModel):
    limit: int = 100
    mode: Optional[str] = None
    thresholds: Optional[Dict[str, float]] = None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _primitive_contract_ready(summary: Dict[str, Any]) -> tuple[bool, List[str]]:
    failures: List[str] = []
    if float(summary.get("schema_coverage", 0.0)) < 0.85:
        failures.append("primitive_schema_coverage_below_0_85")
    if float(summary.get("param_definition_quality", 0.0)) < 0.85:
        failures.append("primitive_param_quality_below_0_85")
    if float(summary.get("description_coverage", 0.0)) < 0.99:
        failures.append("primitive_description_coverage_below_0_99")
    if float(summary.get("score_0_1", 0.0)) < 0.90:
        failures.append("primitive_contract_score_below_0_90")
    if int(summary.get("total_operations", 0)) <= 0:
        failures.append("primitive_operations_missing")
    return len(failures) == 0, failures


def _connectors_reliability_ready(summary: Dict[str, Any]) -> tuple[bool, List[str]]:
    failures: List[str] = []
    if int(summary.get("total_connectors", 0)) <= 0:
        failures.append("no_connectors_initialized")
    if float(summary.get("avg_score_0_1", 0.0)) < 0.90:
        failures.append("connector_reliability_below_0_90")
    return len(failures) == 0, failures


def _orchestration_score_ready(scorecard: Dict[str, Any]) -> tuple[bool, List[str]]:
    failures: List[str] = []
    overall = scorecard.get("overall", {})
    if float(overall.get("score_0_1", 0.0)) < 0.90:
        failures.append("orchestration_score_below_0_90")
    if overall.get("gaps"):
        failures.append("orchestration_gaps_present")
    return len(failures) == 0, failures


def _week3_connectors_ready(
    summary: Dict[str, Any],
    rows: List[Dict[str, Any]],
    *,
    min_avg_score_0_1: float,
    max_auth_incidents: int,
    max_rate_limit_incidents: int,
    max_timeout_incidents: int,
    max_network_incidents: int,
    max_unknown_incidents: int,
    max_repeated_failure_connectors: int,
    max_unhealthy_connectors: int,
    scoring_mode: str = "runtime",
) -> tuple[bool, List[str], Dict[str, Any]]:
    failures: List[str] = []

    incident_totals = dict(summary.get("incident_totals", {}))
    avg_score_0_1 = float(summary.get("avg_score_0_1", 0.0))
    repeated_failure_connectors = sum(1 for r in rows if int(r.get("consecutive_failures", 0)) >= 3)
    if scoring_mode == "offline":
        unhealthy_connectors = sum(
            1
            for r in rows
            if str(r.get("health_state", "")).lower() in {"error", "unhealthy", "disconnected", "auth_required"}
        )
    else:
        unhealthy_connectors = sum(
            1
            for r in rows
            if (not bool(r.get("connected")))
            or str(r.get("health_state", "")).lower() in {"error", "unhealthy", "disconnected", "auth_required"}
        )

    if int(summary.get("total_connectors", 0)) <= 0:
        failures.append("no_connectors_initialized")
    if avg_score_0_1 < min_avg_score_0_1:
        failures.append("connector_avg_score_below_target")
    if int(incident_totals.get("auth", 0)) > max_auth_incidents:
        failures.append("auth_incident_budget_exceeded")
    if int(incident_totals.get("rate_limit", 0)) > max_rate_limit_incidents:
        failures.append("rate_limit_incident_budget_exceeded")
    if int(incident_totals.get("timeout", 0)) > max_timeout_incidents:
        failures.append("timeout_incident_budget_exceeded")
    if int(incident_totals.get("network", 0)) > max_network_incidents:
        failures.append("network_incident_budget_exceeded")
    if int(incident_totals.get("unknown", 0)) > max_unknown_incidents:
        failures.append("unknown_incident_budget_exceeded")
    if repeated_failure_connectors > max_repeated_failure_connectors:
        failures.append("repeated_failure_connector_budget_exceeded")
    if unhealthy_connectors > max_unhealthy_connectors:
        failures.append("unhealthy_connector_budget_exceeded")

    diagnostics = {
        "repeated_failure_connectors": repeated_failure_connectors,
        "unhealthy_connectors": unhealthy_connectors,
    }
    return len(failures) == 0, failures, diagnostics


def _week4_replay_ready(
    trend: Dict[str, Any],
    replay: Dict[str, Any],
    *,
    max_score_drop: float,
    max_pass_rate_drop: float,
    max_latency_increase_ms: float,
    max_llm_call_increase: float,
    max_tool_call_increase: float,
    min_replay_pass_rate: float,
) -> tuple[bool, List[str], Dict[str, Any]]:
    failures: List[str] = []
    delta = trend.get("delta", {}) or {}

    score_drop = max(0.0, -float(delta.get("score", 0.0) or 0.0))
    pass_rate_drop = max(0.0, -float(delta.get("pass_rate", 0.0) or 0.0))
    latency_increase = max(0.0, float(delta.get("latency_ms", 0.0) or 0.0))
    llm_call_increase = max(0.0, float(delta.get("llm_calls", 0.0) or 0.0))
    tool_call_increase = max(0.0, float(delta.get("tool_calls", 0.0) or 0.0))

    replay_pass_rate = float(replay.get("pass_rate", 0.0) or 0.0)
    replay_total = int(replay.get("total", 0) or 0)

    if score_drop > max_score_drop:
        failures.append("score_drop_budget_exceeded")
    if pass_rate_drop > max_pass_rate_drop:
        failures.append("pass_rate_drop_budget_exceeded")
    if latency_increase > max_latency_increase_ms:
        failures.append("latency_increase_budget_exceeded")
    if llm_call_increase > max_llm_call_increase:
        failures.append("llm_call_increase_budget_exceeded")
    if tool_call_increase > max_tool_call_increase:
        failures.append("tool_call_increase_budget_exceeded")
    if replay_pass_rate < min_replay_pass_rate:
        failures.append("replay_pass_rate_below_target")
    if replay_total <= 0:
        failures.append("replay_coverage_missing")

    diagnostics = {
        "score_drop": round(score_drop, 4),
        "pass_rate_drop": round(pass_rate_drop, 4),
        "latency_increase_ms": round(latency_increase, 2),
        "llm_call_increase": round(llm_call_increase, 4),
        "tool_call_increase": round(tool_call_increase, 4),
        "replay_pass_rate": round(replay_pass_rate, 4),
        "replay_total": replay_total,
    }
    return len(failures) == 0, failures, diagnostics


def _week5_ai_engine_ready(
    summary: Dict[str, Any],
    trend: Dict[str, Any],
    *,
    min_total_runs: int,
    min_pass_rate: float,
    min_avg_score: float,
    max_avg_latency_ms: float,
    max_avg_llm_calls: float,
    max_avg_tool_calls: float,
    max_llm_call_increase: float,
    max_tool_call_increase: float,
) -> tuple[bool, List[str], Dict[str, Any]]:
    failures: List[str] = []
    total = int(summary.get("total", 0) or 0)
    pass_rate = float(summary.get("pass_rate", 0.0) or 0.0)
    avg_score = float(summary.get("avg_score", 0.0) or 0.0)
    avg_latency_ms = float(summary.get("avg_latency_ms", 0.0) or 0.0)
    avg_llm_calls = float(summary.get("avg_llm_calls", 0.0) or 0.0)
    avg_tool_calls = float(summary.get("avg_tool_calls", 0.0) or 0.0)

    delta = trend.get("delta", {}) or {}
    llm_call_increase = max(0.0, float(delta.get("llm_calls", 0.0) or 0.0))
    tool_call_increase = max(0.0, float(delta.get("tool_calls", 0.0) or 0.0))
    signals = set(trend.get("signals", []) or [])

    if total < min_total_runs:
        failures.append("insufficient_eval_coverage")
    if pass_rate < min_pass_rate:
        failures.append("pass_rate_below_target")
    if avg_score < min_avg_score:
        failures.append("avg_score_below_target")
    if avg_latency_ms > max_avg_latency_ms:
        failures.append("avg_latency_above_target")
    if avg_llm_calls > max_avg_llm_calls:
        failures.append("avg_llm_calls_above_target")
    if avg_tool_calls > max_avg_tool_calls:
        failures.append("avg_tool_calls_above_target")
    if llm_call_increase > max_llm_call_increase:
        failures.append("llm_call_increase_budget_exceeded")
    if tool_call_increase > max_tool_call_increase:
        failures.append("tool_call_increase_budget_exceeded")
    if "llm_churn_regression" in signals:
        failures.append("llm_churn_regression_detected")

    diagnostics = {
        "total": total,
        "pass_rate": round(pass_rate, 4),
        "avg_score": round(avg_score, 4),
        "avg_latency_ms": round(avg_latency_ms, 2),
        "avg_llm_calls": round(avg_llm_calls, 4),
        "avg_tool_calls": round(avg_tool_calls, 4),
        "llm_call_increase": round(llm_call_increase, 4),
        "tool_call_increase": round(tool_call_increase, 4),
        "signals": sorted(signals),
    }
    return len(failures) == 0, failures, diagnostics


def _verification_safety_ok(verification: Dict[str, Any]) -> bool:
    if "safety_passed" in verification:
        return bool(verification.get("safety_passed"))
    issues = [str(i).lower() for i in (verification.get("issues") or [])]
    if any(
        token in issue
        for issue in issues
        for token in ("unsafe", "policy_violation", "forbidden", "side_effect_precondition_failed")
    ):
        return False
    return bool(verification.get("satisfied", True))


def _week5_benchmark_ready(
    default_run: Dict[str, Any],
    combined_run: Dict[str, Any],
    safety_pass_rate: float,
    replay_churn_avg: float,
    *,
    min_default_pass_rate: float,
    min_combined_pass_rate: float,
    min_safety_pass_rate: float,
    min_replay_churn: float,
) -> tuple[bool, List[str], Dict[str, Any]]:
    failures: List[str] = []
    default_pass_rate = float(default_run.get("pass_rate", 0.0) or 0.0)
    combined_pass_rate = float(combined_run.get("pass_rate", 0.0) or 0.0)

    if default_pass_rate < min_default_pass_rate:
        failures.append("default_benchmark_pass_rate_below_target")
    if combined_pass_rate < min_combined_pass_rate:
        failures.append("combined_benchmark_pass_rate_below_target")
    if safety_pass_rate < min_safety_pass_rate:
        failures.append("replay_safety_pass_rate_below_target")
    if replay_churn_avg < min_replay_churn:
        failures.append("replay_churn_below_target")

    diagnostics = {
        "default_pass_rate": round(default_pass_rate, 4),
        "combined_pass_rate": round(combined_pass_rate, 4),
        "safety_pass_rate": round(safety_pass_rate, 4),
        "replay_churn_avg": round(replay_churn_avg, 4),
    }
    return len(failures) == 0, failures, diagnostics


def _week6_ui_trust_ready(
    summary: Dict[str, Any],
    trend: Dict[str, Any],
    safety_pass_rate: float,
    *,
    min_total_runs: int,
    min_pass_rate: float,
    min_avg_score: float,
    max_avg_latency_ms: float,
    max_avg_llm_calls: float,
    max_avg_tool_calls: float,
    min_replay_safety_pass_rate: float,
) -> tuple[bool, List[str], Dict[str, Any]]:
    failures: List[str] = []
    total = int(summary.get("total", 0) or 0)
    pass_rate = float(summary.get("pass_rate", 0.0) or 0.0)
    avg_score = float(summary.get("avg_score", 0.0) or 0.0)
    avg_latency_ms = float(summary.get("avg_latency_ms", 0.0) or 0.0)
    avg_llm_calls = float(summary.get("avg_llm_calls", 0.0) or 0.0)
    avg_tool_calls = float(summary.get("avg_tool_calls", 0.0) or 0.0)
    signals = set(trend.get("signals", []) or [])

    if total < min_total_runs:
        failures.append("insufficient_eval_coverage")
    if pass_rate < min_pass_rate:
        failures.append("pass_rate_below_target")
    if avg_score < min_avg_score:
        failures.append("avg_score_below_target")
    if avg_latency_ms > max_avg_latency_ms:
        failures.append("avg_latency_above_target")
    if avg_llm_calls > max_avg_llm_calls:
        failures.append("avg_llm_calls_above_target")
    if avg_tool_calls > max_avg_tool_calls:
        failures.append("avg_tool_calls_above_target")
    if safety_pass_rate < min_replay_safety_pass_rate:
        failures.append("replay_safety_pass_rate_below_target")
    if "llm_churn_regression" in signals:
        failures.append("llm_churn_regression_detected")

    diagnostics = {
        "total": total,
        "pass_rate": round(pass_rate, 4),
        "avg_score": round(avg_score, 4),
        "avg_latency_ms": round(avg_latency_ms, 2),
        "avg_llm_calls": round(avg_llm_calls, 4),
        "avg_tool_calls": round(avg_tool_calls, 4),
        "replay_safety_pass_rate": round(safety_pass_rate, 4),
        "signals": sorted(signals),
    }
    return len(failures) == 0, failures, diagnostics


def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(max(0, min(len(ordered) - 1, round((len(ordered) - 1) * q))))
    return float(ordered[idx])


def _week7_performance_ready(
    summary: Dict[str, Any],
    p95_ms: float,
    p99_ms: float,
    *,
    min_total_runs: int,
    min_pass_rate: float,
    min_avg_score: float,
    max_avg_latency_ms: float,
    max_p95_ms: float,
    max_p99_ms: float,
) -> tuple[bool, List[str], Dict[str, Any]]:
    failures: List[str] = []
    total = int(summary.get("total", 0) or 0)
    pass_rate = float(summary.get("pass_rate", 0.0) or 0.0)
    avg_score = float(summary.get("avg_score", 0.0) or 0.0)
    avg_latency_ms = float(summary.get("avg_latency_ms", 0.0) or 0.0)

    if total < min_total_runs:
        failures.append("insufficient_eval_coverage")
    if pass_rate < min_pass_rate:
        failures.append("pass_rate_below_target")
    if avg_score < min_avg_score:
        failures.append("avg_score_below_target")
    if avg_latency_ms > max_avg_latency_ms:
        failures.append("avg_latency_above_target")
    if p95_ms > max_p95_ms:
        failures.append("p95_latency_above_target")
    if p99_ms > max_p99_ms:
        failures.append("p99_latency_above_target")

    diagnostics = {
        "total": total,
        "pass_rate": round(pass_rate, 4),
        "avg_score": round(avg_score, 4),
        "avg_latency_ms": round(avg_latency_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "p99_ms": round(p99_ms, 2),
    }
    return len(failures) == 0, failures, diagnostics


def _classify_incident(error_text: str) -> str:
    msg = (error_text or "").strip().lower()
    if not msg:
        return "none"
    if any(k in msg for k in ("401", "403", "unauthorized", "forbidden", "auth", "token", "oauth")):
        return "auth"
    if any(k in msg for k in ("429", "rate limit", "too many requests", "quota")):
        return "rate_limit"
    if any(k in msg for k in ("timeout", "timed out", "deadline exceeded")):
        return "timeout"
    if any(k in msg for k in ("connection", "dns", "network", "unreachable", "reset by peer")):
        return "network"
    return "unknown"


def _source_aliases(name: str) -> List[str]:
    n = (name or "").strip().lower()
    aliases = {n}
    if n.startswith("google_"):
        aliases.add(n.replace("google_", "", 1))
    if n.startswith("microsoft_"):
        aliases.add(n.replace("microsoft_", "", 1))
    if n == "calendar":
        aliases.add("google_calendar")
        aliases.add("outlook_calendar")
    if n == "contacts":
        aliases.add("google_contacts")
        aliases.add("microsoft_contacts")
    if n == "drive":
        aliases.add("google_drive")
    return sorted(aliases)


def _sync_incident_snapshot() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    sync_engine = getattr(ss, "_sync_engine", None)
    if not sync_engine:
        return out

    try:
        status = sync_engine.status
        states = status.get("states", {}) or {}
    except Exception:
        return out

    failures = getattr(sync_engine, "_consecutive_failures", {}) or {}
    for source, state in states.items():
        err = str(state.get("error") or "")
        incident = _classify_incident(err)
        counts = {
            "auth": 0,
            "rate_limit": 0,
            "timeout": 0,
            "network": 0,
            "unknown": 0,
        }
        if incident in counts:
            counts[incident] = 1
        out[source] = {
            "status": state.get("status"),
            "last_error": err,
            "consecutive_failures": int(failures.get(source, 0)),
            "incidents": counts,
        }
    return out


def _build_orchestration_scorecard(summary: Dict[str, Any], trend: Dict[str, Any]) -> Dict[str, Any]:
    # Targets are intentionally strict to align with "9/10+" quality ambition.
    targets = {
        "min_pass_rate": 0.95,
        "min_avg_score": 0.90,
        "max_avg_latency_ms": 12000.0,
        "min_total_runs": 100,
    }

    total = float(summary.get("total", 0.0))
    pass_rate = float(summary.get("pass_rate", 0.0))
    avg_score = float(summary.get("avg_score", 0.0))
    avg_latency_ms = float(summary.get("avg_latency_ms", 0.0))

    signals = set(trend.get("signals", []))

    pass_rate_norm = _clamp01(_safe_ratio(pass_rate, targets["min_pass_rate"]))
    score_norm = _clamp01(_safe_ratio(avg_score, targets["min_avg_score"]))
    latency_norm = _clamp01(
        _safe_ratio(targets["max_avg_latency_ms"], max(avg_latency_ms, 1.0))
    )
    coverage_norm = _clamp01(_safe_ratio(total, targets["min_total_runs"]))

    weighted = (
        pass_rate_norm * 0.35
        + score_norm * 0.35
        + latency_norm * 0.20
        + coverage_norm * 0.10
    )

    # Regression signals apply a small stability penalty.
    stability_penalty = 0.0
    if "score_regression" in signals:
        stability_penalty += 0.05
    if "pass_rate_regression" in signals:
        stability_penalty += 0.05
    if "latency_regression" in signals:
        stability_penalty += 0.03
    if "llm_churn_regression" in signals:
        stability_penalty += 0.02

    final_score_0_1 = _clamp01(weighted - stability_penalty)
    final_score_10 = round(final_score_0_1 * 10.0, 2)

    gaps: List[str] = []
    if total < targets["min_total_runs"]:
        gaps.append("insufficient_eval_coverage")
    if pass_rate < targets["min_pass_rate"]:
        gaps.append("pass_rate_below_world_class_target")
    if avg_score < targets["min_avg_score"]:
        gaps.append("quality_score_below_world_class_target")
    if avg_latency_ms > targets["max_avg_latency_ms"]:
        gaps.append("latency_above_world_class_target")
    if signals:
        gaps.append("regression_signals_detected")

    return {
        "score_10": final_score_10,
        "score_0_1": round(final_score_0_1, 4),
        "targets": targets,
        "components": {
            "pass_rate": round(pass_rate, 4),
            "avg_score": round(avg_score, 4),
            "avg_latency_ms": round(avg_latency_ms, 2),
            "total_runs": int(total),
            "regression_signals": sorted(signals),
        },
        "gaps": gaps,
    }


def _connector_connected(connector: Any) -> bool:
    if hasattr(connector, "connected"):
        try:
            return bool(getattr(connector, "connected"))
        except Exception:
            return False
    if hasattr(connector, "is_connected"):
        try:
            val = getattr(connector, "is_connected")
            return bool(val() if callable(val) else val)
        except Exception:
            return False
    return False


async def _connector_health_payload(name: str, connector: Any, scoring_mode: str = "runtime") -> Dict[str, Any]:
    connected = _connector_connected(connector)
    check_health_supported = hasattr(connector, "check_health")

    health_state = "unknown"
    health_error: Optional[str] = None
    latency_ms: Optional[float] = None
    status_payload: Dict[str, Any] = {}

    if check_health_supported:
        try:
            health = await connector.check_health()
            if hasattr(health, "status"):
                status = getattr(health, "status")
                health_state = getattr(status, "value", str(status))
            elif hasattr(health, "value"):
                health_state = str(getattr(health, "value"))
            else:
                health_state = str(health)
            if hasattr(health, "latency_ms"):
                latency_ms = getattr(health, "latency_ms")
            if hasattr(health, "to_dict"):
                status_payload = health.to_dict()
        except Exception as e:
            health_state = "error"
            health_error = str(e)

    sync_snapshot = _sync_incident_snapshot()
    aliases = _source_aliases(name)
    matched = [sync_snapshot[a] for a in aliases if a in sync_snapshot]
    consecutive_failures = max((m.get("consecutive_failures", 0) for m in matched), default=0)
    incident_counts = {
        "auth": sum(int(m.get("incidents", {}).get("auth", 0)) for m in matched),
        "rate_limit": sum(int(m.get("incidents", {}).get("rate_limit", 0)) for m in matched),
        "timeout": sum(int(m.get("incidents", {}).get("timeout", 0)) for m in matched),
        "network": sum(int(m.get("incidents", {}).get("network", 0)) for m in matched),
        "unknown": sum(int(m.get("incidents", {}).get("unknown", 0)) for m in matched),
    }
    dominant_incident = "none"
    if sum(incident_counts.values()) > 0:
        dominant_incident = max(incident_counts, key=lambda k: incident_counts[k])

    score = 1.0
    if not connected and scoring_mode != "offline":
        score -= 0.35
    if not check_health_supported and scoring_mode != "offline":
        score -= 0.20
    if health_state in {"error", "unhealthy", "disconnected", "auth_required"}:
        score -= 0.30
    if latency_ms is not None and float(latency_ms) > 2000.0:
        score -= 0.10
    if consecutive_failures >= 3:
        score -= 0.15
    if incident_counts["auth"] > 0:
        score -= 0.10
    if incident_counts["rate_limit"] > 0:
        score -= 0.05
    if incident_counts["timeout"] > 0 or incident_counts["network"] > 0:
        score -= 0.05

    gaps: List[str] = []
    if not connected:
        if scoring_mode == "offline":
            gaps.append("not_configured")
        else:
            gaps.append("not_connected")
    if not check_health_supported and scoring_mode != "offline":
        gaps.append("missing_health_check")
    if health_state in {"error", "unhealthy", "disconnected", "auth_required"}:
        gaps.append("health_not_ok")
    if latency_ms is not None and float(latency_ms) > 2000.0:
        gaps.append("latency_above_target")
    if health_error:
        gaps.append("health_check_failed")
    if consecutive_failures >= 3:
        gaps.append("repeated_sync_failures")
    if incident_counts["auth"] > 0:
        gaps.append("auth_incidents_detected")
    if incident_counts["rate_limit"] > 0:
        gaps.append("rate_limit_incidents_detected")
    if incident_counts["timeout"] > 0:
        gaps.append("timeout_incidents_detected")
    if incident_counts["network"] > 0:
        gaps.append("network_incidents_detected")

    return {
        "connector": name,
        "class": type(connector).__name__,
        "connected": connected,
        "health_state": health_state,
        "health_error": health_error,
        "latency_ms": latency_ms,
        "sync_aliases": aliases,
        "consecutive_failures": consecutive_failures,
        "incident_counts": incident_counts,
        "dominant_incident": dominant_incident,
        "score_0_1": round(_clamp01(score), 4),
        "score_10": round(_clamp01(score) * 10.0, 2),
        "gaps": gaps,
        "status": status_payload,
    }


async def _build_connectors_reliability_report(engine: Any) -> Dict[str, Any]:
    connectors = getattr(engine, "_connectors", {}) if engine else {}
    connected_count = sum(1 for c in connectors.values() if _connector_connected(c))
    scoring_mode = "offline" if connectors and connected_count == 0 else "runtime"
    rows: List[Dict[str, Any]] = []
    for name in sorted(connectors.keys()):
        rows.append(await _connector_health_payload(name, connectors[name], scoring_mode=scoring_mode))

    avg_score = (sum(r["score_0_1"] for r in rows) / len(rows)) if rows else 0.0
    incident_totals = {
        "auth": sum(int(r.get("incident_counts", {}).get("auth", 0)) for r in rows),
        "rate_limit": sum(int(r.get("incident_counts", {}).get("rate_limit", 0)) for r in rows),
        "timeout": sum(int(r.get("incident_counts", {}).get("timeout", 0)) for r in rows),
        "network": sum(int(r.get("incident_counts", {}).get("network", 0)) for r in rows),
        "unknown": sum(int(r.get("incident_counts", {}).get("unknown", 0)) for r in rows),
    }
    gaps: List[str] = []
    if not rows:
        gaps.append("no_connectors_initialized")
    if scoring_mode == "runtime" and avg_score < 0.9:
        gaps.append("connector_reliability_below_world_class_target")
    if incident_totals["auth"] > 0:
        gaps.append("auth_incidents_present")

    return {
        "summary": {
            "total_connectors": len(rows),
            "connected_connectors": connected_count,
            "scoring_mode": scoring_mode,
            "avg_score_0_1": round(avg_score, 4),
            "avg_score_10": round(avg_score * 10.0, 2),
            "incident_totals": incident_totals,
            "gaps": gaps,
        },
        "connectors": rows,
    }


@router.get("/benchmarks/default")
async def orchestration_default_benchmarks():
    cases = [c.__dict__ for c in default_benchmark_cases()]
    return JSONResponse({"cases": cases})


@router.post("/benchmarks/run")
async def orchestration_run_benchmarks(req: BenchmarkRunRequest):
    input_cases = req.cases or [BenchmarkCaseRequest(**c.__dict__) for c in default_benchmark_cases()]
    cases = [
        BenchmarkCase(
            name=c.name,
            llm_calls=c.llm_calls,
            tool_calls=c.tool_calls,
            wall_time_ms=c.wall_time_ms,
            verification=c.verification,
        )
        for c in input_cases
    ]

    th = None
    if req.thresholds:
        th = QualityGateThresholds(
            min_score=float(req.thresholds.get("min_score", 0.75)),
            min_efficiency=float(req.thresholds.get("min_efficiency", 0.25)),
            min_latency=float(req.thresholds.get("min_latency", 0.15)),
            min_churn=float(req.thresholds.get("min_churn", 0.15)),
        )

    result = run_benchmarks(cases, thresholds=th)
    return JSONResponse(result)


@router.get("/quality/thresholds")
async def orchestration_quality_thresholds():
    th = QualityGateThresholds()
    return JSONResponse(
        {
            "min_score": th.min_score,
            "min_efficiency": th.min_efficiency,
            "min_latency": th.min_latency,
            "min_churn": th.min_churn,
        }
    )


@router.get("/quality/history")
async def orchestration_quality_history(limit: int = 50, mode: Optional[str] = None):
    filtered_mode = (mode or "").strip().lower() or None
    rows = _eval_store.recent_runs(limit=max(1, min(limit, 500)), mode=filtered_mode)
    return JSONResponse(
        {
            "total": len(rows),
            "mode": filtered_mode,
            "rows": [
                {
                    "run_id": r.run_id,
                    "workflow_id": r.workflow_id,
                    "session_id": r.session_id,
                    "request_text": r.request_text,
                    "created_at": r.created_at,
                    "score": r.score,
                    "success": r.success,
                    "passed_gate": r.passed_gate,
                    "llm_calls": r.llm_calls,
                    "tool_calls": r.tool_calls,
                    "wall_time_ms": r.wall_time_ms,
                    "orchestration_mode": r.orchestration_mode,
                }
                for r in rows
            ],
        }
    )


@router.get("/quality/release-gate")
async def orchestration_release_gate(lookback: int = 200, mode: Optional[str] = None):
    filtered_mode = (mode or "").strip().lower() or None
    summary = _eval_store.summary(lookback=max(10, min(lookback, 2000)), mode=filtered_mode)

    total = int(summary.get("total", 0))
    pass_rate = float(summary.get("pass_rate", 0.0))
    avg_score = float(summary.get("avg_score", 0.0))
    avg_latency_ms = float(summary.get("avg_latency_ms", 0.0))

    # Generic release criteria for orchestration quality.
    criteria = {
        "min_total_runs": 30,
        "min_pass_rate": 0.90,
        "min_avg_score": 0.80,
        "max_avg_latency_ms": 30000.0,
    }

    failures: List[str] = []
    if total < criteria["min_total_runs"]:
        failures.append("insufficient_run_history")
    if pass_rate < criteria["min_pass_rate"]:
        failures.append("pass_rate_below_target")
    if avg_score < criteria["min_avg_score"]:
        failures.append("avg_score_below_target")
    if avg_latency_ms > criteria["max_avg_latency_ms"]:
        failures.append("avg_latency_above_target")

    return JSONResponse(
        {
            "ready": len(failures) == 0,
            "failures": failures,
            "mode": filtered_mode,
            "criteria": criteria,
            "summary": summary,
        }
    )


@router.get("/quality/trend")
async def orchestration_quality_trend(window: int = 20, lookback: int = 200, mode: Optional[str] = None):
    filtered_mode = (mode or "").strip().lower() or None
    data = _eval_store.trend(
        window=max(5, min(window, 200)),
        lookback=max(20, min(lookback, 2000)),
        mode=filtered_mode,
    )
    return JSONResponse(data)


@router.get("/quality/replay-cases")
async def orchestration_replay_cases(limit: int = 100, mode: Optional[str] = None):
    filtered_mode = (mode or "").strip().lower() or None
    cases = _eval_store.replay_cases(limit=max(1, min(limit, 500)), mode=filtered_mode)
    return JSONResponse({"total": len(cases), "mode": filtered_mode, "cases": cases})


@router.post("/quality/replay-run")
async def orchestration_replay_run(req: ReplayRunRequest):
    filtered_mode = (req.mode or "").strip().lower() or None
    raw_cases = _eval_store.replay_cases(limit=max(1, min(req.limit, 500)), mode=filtered_mode)
    cases = [
        BenchmarkCase(
            name=c.get("name", "replay_case"),
            llm_calls=int(c.get("llm_calls", 0)),
            tool_calls=int(c.get("tool_calls", 0)),
            wall_time_ms=float(c.get("wall_time_ms", 0.0)),
            verification=dict(c.get("verification", {})),
        )
        for c in raw_cases
    ]

    th = None
    if req.thresholds:
        th = QualityGateThresholds(
            min_score=float(req.thresholds.get("min_score", 0.75)),
            min_efficiency=float(req.thresholds.get("min_efficiency", 0.25)),
            min_latency=float(req.thresholds.get("min_latency", 0.15)),
            min_churn=float(req.thresholds.get("min_churn", 0.15)),
        )

    result = run_benchmarks(cases, thresholds=th)
    result["source"] = "eval_store_replay"
    result["mode"] = filtered_mode
    return JSONResponse(result)


@router.get("/policy/recommend")
async def orchestration_policy_recommend(lookback: int = 200, window: int = 20):
    rec = _eval_store.recommend_mode(
        lookback=max(20, min(lookback, 2000)),
        window=max(5, min(window, 200)),
    )
    return JSONResponse(
        {
            "mode": rec.mode,
            "reasons": rec.reasons,
            "summary": rec.summary,
            "trend": rec.trend,
        }
    )


@router.get("/quality/scorecard")
async def orchestration_quality_scorecard(lookback: int = 200, window: int = 20):
    lookback = max(20, min(lookback, 2000))
    window = max(5, min(window, 200))

    overall_summary = _eval_store.summary(lookback=lookback)
    overall_trend = _eval_store.trend(window=window, lookback=lookback)
    overall = _build_orchestration_scorecard(overall_summary, overall_trend)

    by_mode: Dict[str, Any] = {}
    for mode in ("strict", "balanced", "fast"):
        summary = _eval_store.summary(lookback=lookback, mode=mode)
        trend = _eval_store.trend(window=window, lookback=lookback, mode=mode)
        by_mode[mode] = _build_orchestration_scorecard(summary, trend)

    return JSONResponse(
        {
            "pillar": "orchestration",
            "lookback": lookback,
            "window": window,
            "overall": overall,
            "by_mode": by_mode,
        }
    )


@router.get("/quality/primitives-contract")
async def orchestration_primitives_contract_quality():
    engine = ss.get_telic_engine()
    if not engine:
        return JSONResponse(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "error": "engine_not_initialized",
                "summary": {
                    "total_primitives": 0,
                    "total_operations": 0,
                    "score_0_1": 0.0,
                    "score_10": 0.0,
                    "gaps": ["engine_not_initialized"],
                },
                "primitives": [],
            }
        )

    report = audit_primitives(getattr(engine, "_primitives", {}) or {})
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    return JSONResponse(report)


@router.get("/quality/connectors-reliability")
async def orchestration_connectors_reliability():
    engine = ss.get_telic_engine()
    report = await _build_connectors_reliability_report(engine)
    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": report["summary"],
            "connectors": report["connectors"],
        }
    )


@router.get("/quality/week2-gate")
async def orchestration_week2_gate(lookback: int = 200, window: int = 20):
    lookback = max(20, min(lookback, 2000))
    window = max(5, min(window, 200))

    engine = ss.get_telic_engine()

    primitives_report: Dict[str, Any]
    if not engine:
        primitives_report = {
            "summary": {
                "total_primitives": 0,
                "total_operations": 0,
                "schema_coverage": 0.0,
                "description_coverage": 0.0,
                "param_definition_quality": 0.0,
                "score_0_1": 0.0,
                "score_10": 0.0,
                "gaps": ["engine_not_initialized"],
            },
            "primitives": [],
        }
    else:
        primitives_report = audit_primitives(getattr(engine, "_primitives", {}) or {})

    connector_report = await _build_connectors_reliability_report(engine)
    connectors_summary = {
        "total_connectors": connector_report["summary"]["total_connectors"],
        "avg_score_0_1": connector_report["summary"]["avg_score_0_1"],
        "avg_score_10": connector_report["summary"]["avg_score_10"],
    }

    overall_summary = _eval_store.summary(lookback=lookback)
    overall_trend = _eval_store.trend(window=window, lookback=lookback)
    orchestration_score = {
        "pillar": "orchestration",
        "lookback": lookback,
        "window": window,
        "overall": _build_orchestration_scorecard(overall_summary, overall_trend),
    }

    primitives_ready, primitive_failures = _primitive_contract_ready(primitives_report["summary"])
    connectors_ready, connector_failures = _connectors_reliability_ready(connectors_summary)
    orchestration_ready, orchestration_failures = _orchestration_score_ready(orchestration_score)

    failures = primitive_failures + connector_failures + orchestration_failures
    ready = len(failures) == 0

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "checks": {
                "primitives_contract": {
                    "ready": primitives_ready,
                    "summary": primitives_report["summary"],
                    "failures": primitive_failures,
                },
                "connectors_reliability": {
                    "ready": connectors_ready,
                    "summary": connectors_summary,
                    "failures": connector_failures,
                },
                "orchestration_score": {
                    "ready": orchestration_ready,
                    "overall": orchestration_score["overall"],
                    "failures": orchestration_failures,
                },
            },
        }
    )


@router.get("/quality/week3-connectors-gate")
async def orchestration_week3_connectors_gate(
    min_avg_score_0_1: float = 0.92,
    max_auth_incidents: int = 0,
    max_rate_limit_incidents: int = 2,
    max_timeout_incidents: int = 2,
    max_network_incidents: int = 2,
    max_unknown_incidents: int = 3,
    max_repeated_failure_connectors: int = 0,
    max_unhealthy_connectors: int = 0,
):
    engine = ss.get_telic_engine()
    report = await _build_connectors_reliability_report(engine)
    summary = report["summary"]
    rows = report["connectors"]

    criteria = {
        "min_avg_score_0_1": float(min_avg_score_0_1),
        "max_auth_incidents": int(max_auth_incidents),
        "max_rate_limit_incidents": int(max_rate_limit_incidents),
        "max_timeout_incidents": int(max_timeout_incidents),
        "max_network_incidents": int(max_network_incidents),
        "max_unknown_incidents": int(max_unknown_incidents),
        "max_repeated_failure_connectors": int(max_repeated_failure_connectors),
        "max_unhealthy_connectors": int(max_unhealthy_connectors),
    }

    ready, failures, diagnostics = _week3_connectors_ready(
        summary,
        rows,
        min_avg_score_0_1=criteria["min_avg_score_0_1"],
        max_auth_incidents=criteria["max_auth_incidents"],
        max_rate_limit_incidents=criteria["max_rate_limit_incidents"],
        max_timeout_incidents=criteria["max_timeout_incidents"],
        max_network_incidents=criteria["max_network_incidents"],
        max_unknown_incidents=criteria["max_unknown_incidents"],
        max_repeated_failure_connectors=criteria["max_repeated_failure_connectors"],
        max_unhealthy_connectors=criteria["max_unhealthy_connectors"],
        scoring_mode=str(summary.get("scoring_mode", "runtime")),
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "summary": summary,
            "connectors": rows,
        }
    )


@router.get("/quality/week4-replay-gate")
async def orchestration_week4_replay_gate(
    lookback: int = 200,
    window: int = 20,
    replay_limit: int = 100,
    max_score_drop: float = 0.03,
    max_pass_rate_drop: float = 0.03,
    max_latency_increase_ms: float = 1500.0,
    max_llm_call_increase: float = 1.0,
    max_tool_call_increase: float = 4.0,
    min_replay_pass_rate: float = 0.92,
):
    lookback = max(20, min(lookback, 2000))
    window = max(5, min(window, 200))
    replay_limit = max(10, min(replay_limit, 500))

    trend = _eval_store.trend(window=window, lookback=lookback)
    raw_cases = _eval_store.replay_cases(limit=replay_limit)
    cases = [
        BenchmarkCase(
            name=c.get("name", "replay_case"),
            llm_calls=int(c.get("llm_calls", 0)),
            tool_calls=int(c.get("tool_calls", 0)),
            wall_time_ms=float(c.get("wall_time_ms", 0.0)),
            verification=dict(c.get("verification", {})),
        )
        for c in raw_cases
    ]
    replay = run_benchmarks(cases, thresholds=QualityGateThresholds())

    criteria = {
        "max_score_drop": float(max_score_drop),
        "max_pass_rate_drop": float(max_pass_rate_drop),
        "max_latency_increase_ms": float(max_latency_increase_ms),
        "max_llm_call_increase": float(max_llm_call_increase),
        "max_tool_call_increase": float(max_tool_call_increase),
        "min_replay_pass_rate": float(min_replay_pass_rate),
        "lookback": lookback,
        "window": window,
        "replay_limit": replay_limit,
    }

    ready, failures, diagnostics = _week4_replay_ready(
        trend,
        replay,
        max_score_drop=criteria["max_score_drop"],
        max_pass_rate_drop=criteria["max_pass_rate_drop"],
        max_latency_increase_ms=criteria["max_latency_increase_ms"],
        max_llm_call_increase=criteria["max_llm_call_increase"],
        max_tool_call_increase=criteria["max_tool_call_increase"],
        min_replay_pass_rate=criteria["min_replay_pass_rate"],
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "trend": trend,
            "replay": replay,
        }
    )


@router.get("/quality/week5-ai-engine-gate")
async def orchestration_week5_ai_engine_gate(
    lookback: int = 200,
    window: int = 20,
    min_total_runs: int = 80,
    min_pass_rate: float = 0.93,
    min_avg_score: float = 0.88,
    max_avg_latency_ms: float = 15000.0,
    max_avg_llm_calls: float = 8.0,
    max_avg_tool_calls: float = 14.0,
    max_llm_call_increase: float = 1.0,
    max_tool_call_increase: float = 3.0,
):
    lookback = max(20, min(lookback, 2000))
    window = max(5, min(window, 200))
    criteria = {
        "lookback": lookback,
        "window": window,
        "min_total_runs": max(1, int(min_total_runs)),
        "min_pass_rate": float(min_pass_rate),
        "min_avg_score": float(min_avg_score),
        "max_avg_latency_ms": float(max_avg_latency_ms),
        "max_avg_llm_calls": float(max_avg_llm_calls),
        "max_avg_tool_calls": float(max_avg_tool_calls),
        "max_llm_call_increase": float(max_llm_call_increase),
        "max_tool_call_increase": float(max_tool_call_increase),
    }

    summary = _eval_store.summary(lookback=lookback)
    trend = _eval_store.trend(window=window, lookback=lookback)

    ready, failures, diagnostics = _week5_ai_engine_ready(
        summary,
        trend,
        min_total_runs=criteria["min_total_runs"],
        min_pass_rate=criteria["min_pass_rate"],
        min_avg_score=criteria["min_avg_score"],
        max_avg_latency_ms=criteria["max_avg_latency_ms"],
        max_avg_llm_calls=criteria["max_avg_llm_calls"],
        max_avg_tool_calls=criteria["max_avg_tool_calls"],
        max_llm_call_increase=criteria["max_llm_call_increase"],
        max_tool_call_increase=criteria["max_tool_call_increase"],
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "summary": summary,
            "trend": trend,
        }
    )


@router.get("/quality/week5-benchmark-gate")
async def orchestration_week5_benchmark_gate(
    replay_limit: int = 100,
    min_default_pass_rate: float = 0.6,
    min_combined_pass_rate: float = 0.9,
    min_safety_pass_rate: float = 0.95,
    min_replay_churn: float = 0.6,
):
    replay_limit = max(10, min(replay_limit, 500))
    criteria = {
        "replay_limit": replay_limit,
        "min_default_pass_rate": float(min_default_pass_rate),
        "min_combined_pass_rate": float(min_combined_pass_rate),
        "min_safety_pass_rate": float(min_safety_pass_rate),
        "min_replay_churn": float(min_replay_churn),
    }

    default_cases = default_benchmark_cases()
    default_run = run_benchmarks(default_cases, thresholds=QualityGateThresholds())

    raw_replay = _eval_store.replay_cases(limit=replay_limit)
    replay_cases = [
        BenchmarkCase(
            name=c.get("name", "replay_case"),
            llm_calls=int(c.get("llm_calls", 0)),
            tool_calls=int(c.get("tool_calls", 0)),
            wall_time_ms=float(c.get("wall_time_ms", 0.0)),
            verification=dict(c.get("verification", {})),
        )
        for c in raw_replay
    ]
    combined_run = run_benchmarks(default_cases + replay_cases, thresholds=QualityGateThresholds())

    safety_checks = [_verification_safety_ok(dict(c.get("verification", {}))) for c in raw_replay]
    safety_pass_rate = (
        (sum(1 for ok in safety_checks if ok) / len(safety_checks)) if safety_checks else 0.0
    )

    replay_rows = combined_run.get("rows", [])[len(default_cases) :]
    replay_churn_values = [float(r.get("evaluation", {}).get("churn", 0.0) or 0.0) for r in replay_rows]
    replay_churn_avg = (sum(replay_churn_values) / len(replay_churn_values)) if replay_churn_values else 0.0

    ready, failures, diagnostics = _week5_benchmark_ready(
        default_run,
        combined_run,
        safety_pass_rate,
        replay_churn_avg,
        min_default_pass_rate=criteria["min_default_pass_rate"],
        min_combined_pass_rate=criteria["min_combined_pass_rate"],
        min_safety_pass_rate=criteria["min_safety_pass_rate"],
        min_replay_churn=criteria["min_replay_churn"],
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "default_benchmark": {
                "total": default_run.get("total", 0),
                "pass_rate": default_run.get("pass_rate", 0.0),
                "avg_score": default_run.get("avg_score", 0.0),
            },
            "combined_benchmark": {
                "total": combined_run.get("total", 0),
                "pass_rate": combined_run.get("pass_rate", 0.0),
                "avg_score": combined_run.get("avg_score", 0.0),
            },
            "replay": {
                "total": len(raw_replay),
                "safety_pass_rate": round(safety_pass_rate, 4),
                "churn_avg": round(replay_churn_avg, 4),
            },
        }
    )


@router.get("/quality/week6-ui-trust-gate")
async def orchestration_week6_ui_trust_gate(
    lookback: int = 200,
    window: int = 20,
    replay_limit: int = 100,
    min_total_runs: int = 80,
    min_pass_rate: float = 0.9,
    min_avg_score: float = 0.85,
    max_avg_latency_ms: float = 14000.0,
    max_avg_llm_calls: float = 7.0,
    max_avg_tool_calls: float = 12.0,
    min_replay_safety_pass_rate: float = 0.95,
):
    lookback = max(20, min(lookback, 2000))
    window = max(5, min(window, 200))
    replay_limit = max(10, min(replay_limit, 500))

    criteria = {
        "lookback": lookback,
        "window": window,
        "replay_limit": replay_limit,
        "min_total_runs": max(1, int(min_total_runs)),
        "min_pass_rate": float(min_pass_rate),
        "min_avg_score": float(min_avg_score),
        "max_avg_latency_ms": float(max_avg_latency_ms),
        "max_avg_llm_calls": float(max_avg_llm_calls),
        "max_avg_tool_calls": float(max_avg_tool_calls),
        "min_replay_safety_pass_rate": float(min_replay_safety_pass_rate),
    }

    summary = _eval_store.summary(lookback=lookback)
    trend = _eval_store.trend(window=window, lookback=lookback)
    raw_replay = _eval_store.replay_cases(limit=replay_limit)
    safety_checks = [_verification_safety_ok(dict(c.get("verification", {}))) for c in raw_replay]
    safety_pass_rate = (
        (sum(1 for ok in safety_checks if ok) / len(safety_checks)) if safety_checks else 0.0
    )

    ready, failures, diagnostics = _week6_ui_trust_ready(
        summary,
        trend,
        safety_pass_rate,
        min_total_runs=criteria["min_total_runs"],
        min_pass_rate=criteria["min_pass_rate"],
        min_avg_score=criteria["min_avg_score"],
        max_avg_latency_ms=criteria["max_avg_latency_ms"],
        max_avg_llm_calls=criteria["max_avg_llm_calls"],
        max_avg_tool_calls=criteria["max_avg_tool_calls"],
        min_replay_safety_pass_rate=criteria["min_replay_safety_pass_rate"],
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "summary": summary,
            "trend": trend,
            "replay": {
                "total": len(raw_replay),
                "safety_pass_rate": round(safety_pass_rate, 4),
            },
        }
    )


@router.get("/quality/week7-performance-gate")
async def orchestration_week7_performance_gate(
    lookback: int = 200,
    min_total_runs: int = 80,
    min_pass_rate: float = 0.9,
    min_avg_score: float = 0.85,
    max_avg_latency_ms: float = 15000.0,
    max_p95_ms: float = 20000.0,
    max_p99_ms: float = 30000.0,
):
    lookback = max(20, min(lookback, 2000))
    criteria = {
        "lookback": lookback,
        "min_total_runs": max(1, int(min_total_runs)),
        "min_pass_rate": float(min_pass_rate),
        "min_avg_score": float(min_avg_score),
        "max_avg_latency_ms": float(max_avg_latency_ms),
        "max_p95_ms": float(max_p95_ms),
        "max_p99_ms": float(max_p99_ms),
    }

    rows = _eval_store.recent_runs(limit=lookback)
    wall_times = [float(getattr(r, "wall_time_ms", 0.0) or 0.0) for r in rows]
    p95_ms = _percentile(wall_times, 0.95)
    p99_ms = _percentile(wall_times, 0.99)
    summary = _eval_store.summary(lookback=lookback)

    ready, failures, diagnostics = _week7_performance_ready(
        summary,
        p95_ms,
        p99_ms,
        min_total_runs=criteria["min_total_runs"],
        min_pass_rate=criteria["min_pass_rate"],
        min_avg_score=criteria["min_avg_score"],
        max_avg_latency_ms=criteria["max_avg_latency_ms"],
        max_p95_ms=criteria["max_p95_ms"],
        max_p99_ms=criteria["max_p99_ms"],
    )

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": ready,
            "failures": failures,
            "criteria": criteria,
            "diagnostics": diagnostics,
            "summary": summary,
        }
    )


@router.get("/quality/week8-launch-gate")
async def orchestration_week8_launch_gate(
    min_overall_score_10: float = 9.0,
    open_p0: int = 0,
    open_p1: int = 0,
):
    week2 = json.loads((await orchestration_week2_gate(lookback=200, window=20)).body)
    week3 = json.loads((await orchestration_week3_connectors_gate()).body)
    week4 = json.loads((await orchestration_week4_replay_gate()).body)
    week5a = json.loads((await orchestration_week5_ai_engine_gate()).body)
    week5b = json.loads((await orchestration_week5_benchmark_gate()).body)
    week6 = json.loads((await orchestration_week6_ui_trust_gate()).body)
    week7 = json.loads((await orchestration_week7_performance_gate()).body)
    scorecard = json.loads((await orchestration_quality_scorecard(lookback=200, window=20)).body)

    overall_score_10 = float(scorecard.get("overall", {}).get("score_10", 0.0) or 0.0)
    checks = {
        "week2": bool(week2.get("ready")),
        "week3": bool(week3.get("ready")),
        "week4": bool(week4.get("ready")),
        "week5_ai_engine": bool(week5a.get("ready")),
        "week5_benchmark": bool(week5b.get("ready")),
        "week6": bool(week6.get("ready")),
        "week7": bool(week7.get("ready")),
        "overall_score": overall_score_10 >= float(min_overall_score_10),
        "p0_clear": int(open_p0) <= 0,
        "p1_clear": int(open_p1) <= 0,
    }

    failures: List[str] = []
    for key, ok in checks.items():
        if not ok:
            failures.append(f"{key}_not_ready")

    return JSONResponse(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "ready": len(failures) == 0,
            "failures": failures,
            "criteria": {
                "min_overall_score_10": float(min_overall_score_10),
                "max_open_p0": 0,
                "max_open_p1": 0,
            },
            "diagnostics": {
                "overall_score_10": round(overall_score_10, 2),
                "open_p0": int(open_p0),
                "open_p1": int(open_p1),
            },
            "checks": checks,
        }
    )
