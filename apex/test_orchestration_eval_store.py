from pathlib import Path

from orchestration.eval_store import OrchestrationEvalStore
from server_state import ReactApproveRequest, ReactRequest


def test_eval_store_record_and_summary(tmp_path: Path):
    store = OrchestrationEvalStore(tmp_path / "orch_eval.db")

    store.record_run(
        workflow_id="wf_1",
        session_id="s_1",
        request_text="create and send report",
        evaluation={
            "score": 0.88,
            "success": True,
            "efficiency": 0.7,
            "latency": 0.8,
            "churn": 0.6,
            "notes": {"llm_calls": 6, "tool_calls": 12, "wall_time_ms": 11000},
        },
        verification={"satisfied": True, "score": 0.9},
        gate={"passed": True, "failures": []},
    )

    rows = store.recent_runs(limit=5)
    assert len(rows) == 1
    assert rows[0].workflow_id == "wf_1"
    assert rows[0].orchestration_mode == "balanced"

    summary = store.summary(lookback=10)
    assert summary["total"] == 1
    assert summary["passed"] == 1
    assert summary["avg_score"] > 0.0


def test_eval_store_trend_and_replay_cases(tmp_path: Path):
    store = OrchestrationEvalStore(tmp_path / "orch_eval.db")

    for i in range(12):
        store.record_run(
            workflow_id=f"wf_{i}",
            session_id="s_1",
            request_text=f"request_{i}",
            evaluation={
                "score": 0.9 - (i * 0.01),
                "success": True,
                "efficiency": 0.7,
                "latency": 0.8,
                "churn": 0.6,
                "notes": {"llm_calls": 6 + (i % 2), "tool_calls": 12 + i, "wall_time_ms": 10000 + i * 100},
            },
            verification={"satisfied": True, "score": 0.9},
            gate={"passed": True, "failures": []},
        )

    trend = store.trend(window=5, lookback=12)
    assert "recent" in trend
    assert "baseline" in trend
    assert "delta" in trend

    replay = store.replay_cases(limit=5)
    assert len(replay) == 5
    assert "verification" in replay[0]


def test_request_models_support_orchestration_mode():
    r = ReactRequest(message="hello", orchestration_mode="fast")
    a = ReactApproveRequest(approved=True, orchestration_mode="strict")

    assert r.orchestration_mode == "fast"
    assert a.orchestration_mode == "strict"


def test_eval_store_recommend_mode_prefers_strict_on_quality_regression(tmp_path: Path):
    store = OrchestrationEvalStore(tmp_path / "orch_eval.db")

    # Insert baseline (older) first, then degraded recent runs.
    for i in range(20):
        store.record_run(
            workflow_id=f"base_{i}",
            session_id="s_1",
            request_text=f"baseline_{i}",
            evaluation={
                "score": 0.92,
                "success": True,
                "efficiency": 0.75,
                "latency": 0.85,
                "churn": 0.7,
                "notes": {"llm_calls": 5, "tool_calls": 10, "wall_time_ms": 9000},
            },
            verification={"satisfied": True, "score": 0.92},
            gate={"passed": True, "failures": []},
        )

    for i in range(20):
        store.record_run(
            workflow_id=f"recent_{i}",
            session_id="s_1",
            request_text=f"recent_bad_{i}",
            evaluation={
                "score": 0.68,
                "success": False,
                "efficiency": 0.5,
                "latency": 0.7,
                "churn": 0.5,
                "notes": {"llm_calls": 7, "tool_calls": 16, "wall_time_ms": 13000},
            },
            verification={"satisfied": False, "score": 0.68},
            gate={"passed": False, "failures": ["low_score"]},
        )

    rec = store.recommend_mode(lookback=80, window=20)
    assert rec.mode == "strict"
    assert rec.reasons


def test_eval_store_recommend_mode_prefers_fast_on_latency_regression(tmp_path: Path):
    store = OrchestrationEvalStore(tmp_path / "orch_eval.db")

    for i in range(20):
        store.record_run(
            workflow_id=f"base_fast_{i}",
            session_id="s_1",
            request_text=f"baseline_fast_{i}",
            evaluation={
                "score": 0.9,
                "success": True,
                "efficiency": 0.74,
                "latency": 0.84,
                "churn": 0.7,
                "notes": {"llm_calls": 5, "tool_calls": 9, "wall_time_ms": 12000},
            },
            verification={"satisfied": True, "score": 0.9},
            gate={"passed": True, "failures": []},
        )

    for i in range(20):
        store.record_run(
            workflow_id=f"recent_fast_{i}",
            session_id="s_1",
            request_text=f"recent_slow_{i}",
            evaluation={
                "score": 0.9,
                "success": True,
                "efficiency": 0.72,
                "latency": 0.75,
                "churn": 0.7,
                "notes": {"llm_calls": 5, "tool_calls": 10, "wall_time_ms": 22000},
            },
            verification={"satisfied": True, "score": 0.9},
            gate={"passed": True, "failures": []},
        )

    rec = store.recommend_mode(lookback=80, window=20)
    assert rec.mode == "fast"
    assert rec.reasons


def test_eval_store_mode_filtered_views(tmp_path: Path):
    store = OrchestrationEvalStore(tmp_path / "orch_eval.db")

    for i in range(6):
        store.record_run(
            workflow_id=f"wf_s_{i}",
            session_id="s_1",
            request_text=f"strict_{i}",
            evaluation={
                "score": 0.91,
                "success": True,
                "efficiency": 0.75,
                "latency": 0.85,
                "churn": 0.7,
                "notes": {"llm_calls": 5, "tool_calls": 8, "wall_time_ms": 9000},
            },
            verification={"satisfied": True, "score": 0.91},
            gate={"passed": True, "failures": []},
            orchestration_mode="strict",
        )

    for i in range(4):
        store.record_run(
            workflow_id=f"wf_f_{i}",
            session_id="s_1",
            request_text=f"fast_{i}",
            evaluation={
                "score": 0.85,
                "success": True,
                "efficiency": 0.7,
                "latency": 0.78,
                "churn": 0.65,
                "notes": {"llm_calls": 4, "tool_calls": 7, "wall_time_ms": 7000},
            },
            verification={"satisfied": True, "score": 0.85},
            gate={"passed": True, "failures": []},
            orchestration_mode="fast",
        )

    strict_rows = store.recent_runs(limit=20, mode="strict")
    assert len(strict_rows) == 6
    assert all(r.orchestration_mode == "strict" for r in strict_rows)

    fast_summary = store.summary(lookback=20, mode="fast")
    assert fast_summary["total"] == 4
    assert fast_summary["mode"] == "fast"

    strict_trend = store.trend(window=3, lookback=6, mode="strict")
    assert strict_trend["mode"] == "strict"

    fast_replay = store.replay_cases(limit=10, mode="fast")
    assert len(fast_replay) == 4
    assert all(c["orchestration_mode"] == "fast" for c in fast_replay)
