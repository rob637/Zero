from __future__ import annotations

import asyncio
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

    plane._repair_workers_in_flight = 1
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


def test_repair_worker_never_exceeds_configured_concurrency(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()
    plane._repair_concurrency = 2
    plane._repair_semaphore = asyncio.Semaphore(plane._repair_concurrency)

    active = 0
    max_active = 0
    completed: list[str] = []

    async def fake_execute(repair_id: str) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        completed.append(repair_id)
        active -= 1

    plane._execute_repair = fake_execute  # type: ignore[assignment]

    async def run_test() -> None:
        plane._ensure_repair_worker()
        for idx in range(6):
            await plane._repair_queue.put(f"repair-{idx}")

        while len(completed) < 6:
            await asyncio.sleep(0.01)

        if plane._repair_worker_task is not None:
            plane._repair_worker_task.cancel()
            try:
                await plane._repair_worker_task
            except asyncio.CancelledError:
                pass

    asyncio.run(run_test())

    assert max_active <= plane._repair_concurrency
    assert plane._repair_max_active_observed <= plane._repair_concurrency
    assert len(completed) == 6


def test_repair_metrics_include_peak_worker_observation(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()
    plane._repair_max_active_observed = 2

    metrics = plane._compute_repair_metrics([])
    assert metrics["max_active_observed"] == 2


def test_run_history_retention_keeps_active_and_newest_terminal(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()
    plane._max_runs_history = 3

    state = plane._default_state()
    state["runs"] = [
        {"id": "run-old-queued", "status": "queued", "created_at": _iso_age(300)},
        {"id": "run-new-running", "status": "running", "created_at": _iso_age(20)},
        {"id": "run-failed-old", "status": "failed", "created_at": _iso_age(250)},
        {"id": "run-failed-mid", "status": "failed", "created_at": _iso_age(150)},
        {"id": "run-passed-new", "status": "passed", "created_at": _iso_age(30)},
    ]
    plane._save_state(state)

    saved = plane._load_state()
    runs = saved["runs"]
    kept_ids = {item["id"] for item in runs}

    assert len(runs) == 3
    assert "run-old-queued" in kept_ids
    assert "run-new-running" in kept_ids
    assert "run-passed-new" in kept_ids


def test_repair_history_retention_keeps_in_progress_and_newest_terminal(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()
    plane._max_repairs_history = 3

    state = plane._default_state()
    state["repairs"] = [
        {"id": "repair-old-queued", "status": "queued", "created_at": _iso_age(400)},
        {"id": "repair-new-progress", "status": "in_progress", "created_at": _iso_age(20)},
        {"id": "repair-blocked-old", "status": "blocked", "created_at": _iso_age(250)},
        {"id": "repair-validated-mid", "status": "validated", "created_at": _iso_age(120)},
        {"id": "repair-validated-new", "status": "validated", "created_at": _iso_age(30)},
    ]
    plane._save_state(state)

    saved = plane._load_state()
    repairs = saved["repairs"]
    kept_ids = {item["id"] for item in repairs}

    assert len(repairs) == 3
    assert "repair-old-queued" in kept_ids
    assert "repair-new-progress" in kept_ids
    assert "repair-validated-new" in kept_ids
