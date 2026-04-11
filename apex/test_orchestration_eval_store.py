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
