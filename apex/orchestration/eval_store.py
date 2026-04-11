"""Persistent store for orchestration run evaluations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class EvaluationRun:
    run_id: str
    workflow_id: str
    session_id: str
    request_text: str
    created_at: str
    score: float
    success: bool
    passed_gate: bool
    llm_calls: int
    tool_calls: int
    wall_time_ms: float
    orchestration_mode: str
    evaluation: Dict[str, Any]
    verification: Dict[str, Any]
    gate: Dict[str, Any]


@dataclass
class PolicyRecommendation:
    mode: str
    reasons: List[str]
    summary: Dict[str, Any]
    trend: Dict[str, Any]


class OrchestrationEvalStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orchestration_runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    request_text TEXT,
                    created_at TEXT NOT NULL,
                    score REAL NOT NULL,
                    success INTEGER NOT NULL,
                    passed_gate INTEGER NOT NULL,
                    llm_calls INTEGER NOT NULL,
                    tool_calls INTEGER NOT NULL,
                    wall_time_ms REAL NOT NULL,
                    orchestration_mode TEXT NOT NULL DEFAULT 'balanced',
                    evaluation_json TEXT,
                    verification_json TEXT,
                    gate_json TEXT
                )
                """
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(orchestration_runs)").fetchall()}
            if "orchestration_mode" not in cols:
                conn.execute(
                    """
                    ALTER TABLE orchestration_runs
                    ADD COLUMN orchestration_mode TEXT NOT NULL DEFAULT 'balanced'
                    """
                )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orch_runs_created
                ON orchestration_runs (created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orch_runs_mode_created
                ON orchestration_runs (orchestration_mode, created_at DESC)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_orch_runs_workflow
                ON orchestration_runs (workflow_id, created_at DESC)
                """
            )

    def record_run(
        self,
        *,
        workflow_id: str,
        session_id: str,
        request_text: str,
        evaluation: Dict[str, Any],
        verification: Dict[str, Any],
        gate: Dict[str, Any],
        orchestration_mode: str = "balanced",
    ) -> str:
        created_at = datetime.now(timezone.utc).isoformat()
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        notes = dict(evaluation.get("notes", {}) or {})

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orchestration_runs (
                    run_id, workflow_id, session_id, request_text, created_at,
                    score, success, passed_gate, llm_calls, tool_calls, wall_time_ms,
                    orchestration_mode, evaluation_json, verification_json, gate_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    workflow_id,
                    session_id,
                    request_text[:500],
                    created_at,
                    float(evaluation.get("score", 0.0)),
                    1 if bool(evaluation.get("success", False)) else 0,
                    1 if bool(gate.get("passed", False)) else 0,
                    int(notes.get("llm_calls", 0)),
                    int(notes.get("tool_calls", 0)),
                    float(notes.get("wall_time_ms", 0.0)),
                    (orchestration_mode or "balanced")[:32],
                    json.dumps(evaluation, default=str),
                    json.dumps(verification, default=str),
                    json.dumps(gate, default=str),
                ),
            )
        return run_id

    def recent_runs(self, limit: int = 50, mode: Optional[str] = None) -> List[EvaluationRun]:
        with self._connect() as conn:
            if mode:
                rows = conn.execute(
                    """
                    SELECT run_id, workflow_id, session_id, request_text, created_at,
                           score, success, passed_gate, llm_calls, tool_calls, wall_time_ms,
                           orchestration_mode, evaluation_json, verification_json, gate_json
                    FROM orchestration_runs
                    WHERE orchestration_mode = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (mode, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT run_id, workflow_id, session_id, request_text, created_at,
                           score, success, passed_gate, llm_calls, tool_calls, wall_time_ms,
                           orchestration_mode, evaluation_json, verification_json, gate_json
                    FROM orchestration_runs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        return [self._row_to_run(r) for r in rows]

    def summary(self, lookback: int = 200, mode: Optional[str] = None) -> Dict[str, Any]:
        rows = self.recent_runs(limit=lookback, mode=mode)
        total = len(rows)
        if total == 0:
            return {
                "total": 0,
                "pass_rate": 0.0,
                "avg_score": 0.0,
                "avg_latency_ms": 0.0,
                "avg_llm_calls": 0.0,
                "avg_tool_calls": 0.0,
                "mode": mode,
            }

        passed = sum(1 for r in rows if r.passed_gate)
        avg_score = sum(r.score for r in rows) / total
        avg_latency = sum(r.wall_time_ms for r in rows) / total
        avg_llm = sum(r.llm_calls for r in rows) / total
        avg_tool = sum(r.tool_calls for r in rows) / total

        return {
            "total": total,
            "passed": passed,
            "pass_rate": passed / total,
            "avg_score": avg_score,
            "avg_latency_ms": avg_latency,
            "avg_llm_calls": avg_llm,
            "avg_tool_calls": avg_tool,
            "mode": mode,
        }

    def trend(self, window: int = 20, lookback: int = 200, mode: Optional[str] = None) -> Dict[str, Any]:
        """Return recent-vs-baseline trend to detect regressions quickly."""
        rows = self.recent_runs(limit=max(lookback, window * 2), mode=mode)
        if len(rows) < 2:
            return {
                "window": window,
                "mode": mode,
                "recent": {},
                "baseline": {},
                "delta": {},
                "signals": [],
            }

        recent = rows[:window]
        baseline = rows[window: window * 2] if len(rows) >= window * 2 else rows[window:]
        if not baseline:
            baseline = rows[window:]

        def _avg(vals):
            return sum(vals) / max(len(vals), 1)

        recent_stats = {
            "score": _avg([r.score for r in recent]),
            "pass_rate": _avg([1.0 if r.passed_gate else 0.0 for r in recent]),
            "latency_ms": _avg([r.wall_time_ms for r in recent]),
            "llm_calls": _avg([r.llm_calls for r in recent]),
            "tool_calls": _avg([r.tool_calls for r in recent]),
        }
        baseline_stats = {
            "score": _avg([r.score for r in baseline]),
            "pass_rate": _avg([1.0 if r.passed_gate else 0.0 for r in baseline]),
            "latency_ms": _avg([r.wall_time_ms for r in baseline]),
            "llm_calls": _avg([r.llm_calls for r in baseline]),
            "tool_calls": _avg([r.tool_calls for r in baseline]),
        }

        delta = {
            "score": recent_stats["score"] - baseline_stats["score"],
            "pass_rate": recent_stats["pass_rate"] - baseline_stats["pass_rate"],
            "latency_ms": recent_stats["latency_ms"] - baseline_stats["latency_ms"],
            "llm_calls": recent_stats["llm_calls"] - baseline_stats["llm_calls"],
            "tool_calls": recent_stats["tool_calls"] - baseline_stats["tool_calls"],
        }

        signals = []
        if delta["score"] < -0.05:
            signals.append("score_regression")
        if delta["pass_rate"] < -0.05:
            signals.append("pass_rate_regression")
        if delta["latency_ms"] > 3000:
            signals.append("latency_regression")
        if delta["llm_calls"] > 1.5:
            signals.append("llm_churn_regression")

        return {
            "window": window,
            "mode": mode,
            "recent": recent_stats,
            "baseline": baseline_stats,
            "delta": delta,
            "signals": signals,
        }

    def replay_cases(self, limit: int = 100, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """Export recent run snapshots as benchmark/replay case payloads."""
        rows = self.recent_runs(limit=max(1, min(limit, 2000)), mode=mode)
        return [
            {
                "name": r.request_text[:80] or r.run_id,
                "llm_calls": r.llm_calls,
                "tool_calls": r.tool_calls,
                "wall_time_ms": r.wall_time_ms,
                "verification": r.verification,
                "orchestration_mode": r.orchestration_mode,
                "meta": {
                    "run_id": r.run_id,
                    "workflow_id": r.workflow_id,
                    "created_at": r.created_at,
                },
            }
            for r in rows
        ]

    def recommend_mode(self, lookback: int = 200, window: int = 20) -> PolicyRecommendation:
        """Recommend orchestration mode from quality and trend signals.

        Modes:
        - strict: prioritize correctness/stability when quality regresses
        - balanced: default for healthy operation
        - fast: prioritize latency when quality is strong but latency drifts
        """
        summary = self.summary(lookback=lookback)
        trend = self.trend(window=window, lookback=lookback)
        signals = set(trend.get("signals", []))

        reasons: List[str] = []
        mode = "balanced"

        total = int(summary.get("total", 0))
        pass_rate = float(summary.get("pass_rate", 0.0))
        avg_score = float(summary.get("avg_score", 0.0))
        avg_latency_ms = float(summary.get("avg_latency_ms", 0.0))

        if total < 30:
            reasons.append("insufficient_history_default_balanced")
            return PolicyRecommendation(mode=mode, reasons=reasons, summary=summary, trend=trend)

        if "score_regression" in signals or "pass_rate_regression" in signals:
            mode = "strict"
            reasons.append("quality_regression_detected")
        elif avg_score < 0.78 or pass_rate < 0.88:
            mode = "strict"
            reasons.append("quality_below_target")
        elif "latency_regression" in signals and avg_score >= 0.82 and pass_rate >= 0.9:
            mode = "fast"
            reasons.append("latency_regression_with_strong_quality")
        elif avg_latency_ms > 30000 and avg_score >= 0.82 and pass_rate >= 0.9:
            mode = "fast"
            reasons.append("latency_above_target_with_strong_quality")
        else:
            reasons.append("stable_balanced_operation")

        if "llm_churn_regression" in signals and mode == "fast":
            mode = "balanced"
            reasons.append("llm_churn_regression_avoids_fast_mode")

        return PolicyRecommendation(mode=mode, reasons=reasons, summary=summary, trend=trend)

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> EvaluationRun:
        return EvaluationRun(
            run_id=row["run_id"],
            workflow_id=row["workflow_id"],
            session_id=row["session_id"],
            request_text=row["request_text"],
            created_at=row["created_at"],
            score=float(row["score"]),
            success=bool(row["success"]),
            passed_gate=bool(row["passed_gate"]),
            llm_calls=int(row["llm_calls"]),
            tool_calls=int(row["tool_calls"]),
            wall_time_ms=float(row["wall_time_ms"]),
            orchestration_mode=str(row["orchestration_mode"] or "balanced"),
            evaluation=json.loads(row["evaluation_json"] or "{}"),
            verification=json.loads(row["verification_json"] or "{}"),
            gate=json.loads(row["gate_json"] or "{}"),
        )
