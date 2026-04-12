from __future__ import annotations

import asyncio
import sys
from pathlib import Path

APEX_ROOT = Path(__file__).resolve().parent / "apex"
if str(APEX_ROOT) not in sys.path:
    sys.path.insert(0, str(APEX_ROOT))

from harness import control_plane as cp


def _configure_temp_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(cp, "CONTROL_STATE_FILE", tmp_path / "control_plane_state.json")
    monkeypatch.setattr(cp, "DEFAULT_SCENARIO_FILE", tmp_path / "regression_scenarios.json")
    monkeypatch.setattr(cp, "RUN_REPORTS_DIR", tmp_path / "runs")
    monkeypatch.setattr(cp, "LATEST_REPORTS_DIR", tmp_path / "latest")


def test_repair_queue_burnin_drains_under_bounded_concurrency(tmp_path: Path, monkeypatch) -> None:
    _configure_temp_paths(tmp_path, monkeypatch)
    plane = cp.HarnessControlPlane()
    plane._repair_concurrency = 3
    plane._repair_semaphore = asyncio.Semaphore(plane._repair_concurrency)

    active = 0
    peak_active = 0
    completed: list[str] = []

    async def fake_execute(repair_id: str) -> None:
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        await asyncio.sleep(0.005)
        completed.append(repair_id)
        active -= 1

    plane._execute_repair = fake_execute  # type: ignore[assignment]

    async def run_burnin() -> None:
        plane._ensure_repair_worker()
        total = 120
        for idx in range(total):
            await plane._repair_queue.put(f"repair-{idx}")

        while len(completed) < total:
            await asyncio.sleep(0.01)

        # Allow task callbacks to settle and metrics to update.
        await asyncio.sleep(0.02)

        if plane._repair_worker_task is not None:
            plane._repair_worker_task.cancel()
            try:
                await plane._repair_worker_task
            except asyncio.CancelledError:
                pass

    asyncio.run(run_burnin())

    assert len(completed) == 120
    assert peak_active <= plane._repair_concurrency
    assert plane._repair_max_active_observed <= plane._repair_concurrency
    assert plane._repair_queue.qsize() == 0
