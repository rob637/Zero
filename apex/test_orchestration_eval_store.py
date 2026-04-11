from pathlib import Path

from orchestration.eval_store import OrchestrationEvalStore


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
