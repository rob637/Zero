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
    evaluation: Dict[str, Any]
    verification: Dict[str, Any]
    gate: Dict[str, Any]


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
                    evaluation_json TEXT,
                    verification_json TEXT,
                    gate_json TEXT
                )
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
                    evaluation_json, verification_json, gate_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    json.dumps(evaluation, default=str),
                    json.dumps(verification, default=str),
                    json.dumps(gate, default=str),
                ),
            )
        return run_id

    def recent_runs(self, limit: int = 50) -> List[EvaluationRun]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, workflow_id, session_id, request_text, created_at,
                       score, success, passed_gate, llm_calls, tool_calls, wall_time_ms,
                       evaluation_json, verification_json, gate_json
                FROM orchestration_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._row_to_run(r) for r in rows]

    def summary(self, lookback: int = 200) -> Dict[str, Any]:
        rows = self.recent_runs(limit=lookback)
        total = len(rows)
        if total == 0:
            return {
                "total": 0,
                "pass_rate": 0.0,
                "avg_score": 0.0,
                "avg_latency_ms": 0.0,
                "avg_llm_calls": 0.0,
                "avg_tool_calls": 0.0,
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
        }

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
            evaluation=json.loads(row["evaluation_json"] or "{}"),
            verification=json.loads(row["verification_json"] or "{}"),
            gate=json.loads(row["gate_json"] or "{}"),
        )
