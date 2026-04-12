from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

APEX_ROOT = Path(__file__).resolve().parent / "apex"
if str(APEX_ROOT) not in sys.path:
    sys.path.insert(0, str(APEX_ROOT))

from harness import control_plane as cp


def _iso_age(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _configure_temp_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cp, "CONTROL_STATE_FILE", tmp_path / "control_plane_state.json")
    monkeypatch.setattr(cp, "DEFAULT_SCENARIO_FILE", tmp_path / "regression_scenarios.json")
    monkeypatch.setattr(cp, "RUN_REPORTS_DIR", tmp_path / "runs")
    monkeypatch.setattr(cp, "LATEST_REPORTS_DIR", tmp_path / "latest")


def test_run_watchdog_transitions_stale_running_to_error(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()

    stale_seconds = plane._run_timeout_seconds + 120
    state = plane._default_state()
    state["runs"] = [
        {
            "id": "run-stale",
            "status": "running",
            "created_at": _iso_age(stale_seconds + 60),
            "started_at": _iso_age(stale_seconds),
            "summary": {},
        }
    ]
    plane._save_state(state)

    runs = plane.get_runs()
    assert runs["items"][0]["status"] == "error"
    watchdog = runs["items"][0].get("watchdog", {})
    assert watchdog.get("timed_out") is True
    assert watchdog.get("scope") == "execution"
    assert float(watchdog.get("age_seconds", 0.0)) >= plane._run_timeout_seconds


def test_repair_watchdog_blocks_stale_in_progress_repair(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()

    stale_seconds = plane._repair_timeout_seconds + 120
    state = plane._default_state()
    state["repairs"] = [
        {
            "id": "repair-stale",
            "status": "in_progress",
            "created_at": _iso_age(stale_seconds + 60),
            "started_at": _iso_age(stale_seconds),
            "transitions": [{"status": "queued", "at": _iso_age(stale_seconds + 300)}],
        }
    ]
    plane._save_state(state)

    insights = plane.get_failure_insights()
    repair = insights["repairs"][0]
    assert repair["status"] == "blocked"
    assert "watchdog timeout" in str(repair.get("blocked_reason", "")).lower()
    transitions = repair.get("transitions", [])
    assert any(item.get("reason") == "watchdog_timeout" for item in transitions)


def test_repair_metrics_invariants_include_worker_and_queue_state(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()

    now = datetime.now(timezone.utc)
    repairs = [
        {
            "id": "repair-1",
            "status": "validated",
            "validation": {"improved": True},
            "started_at": (now - timedelta(seconds=30)).isoformat(),
            "finished_at": now.isoformat(),
        },
        {
            "id": "repair-2",
            "status": "blocked",
            "validation": {"improved": False},
            "started_at": (now - timedelta(seconds=10)).isoformat(),
            "finished_at": now.isoformat(),
        },
        {
            "id": "repair-3",
            "status": "queued",
        },
    ]

    plane._active_repair_tasks["repair-active"] = object()  # type: ignore[assignment]
    plane._repair_queue.put_nowait("repair-queued")

    metrics = plane._compute_repair_metrics(repairs)
    assert metrics["configured_workers"] == plane._repair_concurrency
    assert metrics["active_workers"] == 1
    assert metrics["queue_depth"] == 1
    assert 0.0 <= float(metrics["validated_rate"]) <= 1.0
    assert 0.0 <= float(metrics["improvement_rate"]) <= 1.0
    assert metrics["completed"] == 2


def test_runtime_diagnostics_exposes_counts_ages_and_ids(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()

    state = plane._default_state()
    state["runs"] = [
        {
            "id": "run-queued",
            "status": "queued",
            "created_at": _iso_age(90),
        },
        {
            "id": "run-active",
            "status": "running",
            "created_at": _iso_age(120),
            "started_at": _iso_age(60),
        },
    ]
    state["repairs"] = [
        {
            "id": "repair-queued",
            "status": "queued",
            "created_at": _iso_age(45),
        },
        {
            "id": "repair-active",
            "status": "in_progress",
            "created_at": _iso_age(90),
            "started_at": _iso_age(30),
        },
    ]
    plane._save_state(state)
    plane._active_repair_tasks["repair-active"] = object()  # type: ignore[assignment]

    diagnostics = plane.get_runtime_diagnostics()

    assert diagnostics["runs"]["queued"] == 1
    assert diagnostics["runs"]["running"] == 1
    assert diagnostics["repairs"]["queued"] == 1
    assert diagnostics["repairs"]["in_progress"] == 1
    assert "run-active" in diagnostics["runs"]["running_ids"]
    assert "repair-active" in diagnostics["repairs"]["active_task_ids"]
    assert diagnostics["runs"]["running_age_seconds"]["max"] >= diagnostics["runs"]["running_age_seconds"]["avg"]
    assert diagnostics["repairs"]["in_progress_age_seconds"]["max"] >= diagnostics["repairs"]["in_progress_age_seconds"]["avg"]
