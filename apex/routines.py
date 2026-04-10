"""
Routines — Scheduled prompts that run automatically.

"Every Monday 8am, give me a week preview."
"Every Friday 5pm, summarize what I shipped."
"Every morning, check my calendar and email."

Architecture:
  RoutineStore  — SQLite CRUD for routine definitions
  RoutineRunner — asyncio loop that checks schedules and fires prompts
"""

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "sqlite" / "routines.db"

# ---------------------------------------------------------------------------
# Schedule types
# ---------------------------------------------------------------------------

class ScheduleType(str, Enum):
    DAILY = "daily"          # Every day at a specific time
    WEEKDAYS = "weekdays"    # Mon-Fri at a specific time
    WEEKLY = "weekly"        # Specific day(s) of week at a time
    INTERVAL = "interval"    # Every N minutes


# ---------------------------------------------------------------------------
# Routine Store — SQLite persistence
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routines (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    schedule    TEXT NOT NULL,       -- JSON: {"type": "daily", "time": "08:00", ...}
    enabled     INTEGER NOT NULL DEFAULT 1,
    last_run    TEXT,                -- ISO 8601
    last_result TEXT,                -- last execution result (truncated)
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS routine_runs (
    id          TEXT PRIMARY KEY,
    routine_id  TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running',   -- running, completed, failed
    result      TEXT,
    FOREIGN KEY (routine_id) REFERENCES routines(id) ON DELETE CASCADE
);
"""


class RoutineStore:
    """SQLite-backed CRUD for routines."""

    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def create(self, name: str, prompt: str, schedule: dict) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        routine = {
            "id": str(uuid.uuid4()),
            "name": name,
            "prompt": prompt,
            "schedule": json.dumps(schedule),
            "enabled": True,
            "last_run": None,
            "last_result": None,
            "created_at": now,
            "updated_at": now,
        }
        self._conn.execute(
            """INSERT INTO routines (id, name, prompt, schedule, enabled, last_run, last_result, created_at, updated_at)
               VALUES (:id, :name, :prompt, :schedule, :enabled, :last_run, :last_result, :created_at, :updated_at)""",
            routine,
        )
        self._conn.commit()
        routine["schedule"] = schedule
        return routine

    def list(self) -> List[dict]:
        rows = self._conn.execute("SELECT * FROM routines ORDER BY created_at DESC").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get(self, routine_id: str) -> Optional[dict]:
        row = self._conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def update(self, routine_id: str, **fields) -> Optional[dict]:
        allowed = {"name", "prompt", "schedule", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get(routine_id)
        if "schedule" in updates and isinstance(updates["schedule"], dict):
            updates["schedule"] = json.dumps(updates["schedule"])
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [routine_id]
        self._conn.execute(f"UPDATE routines SET {set_clause} WHERE id = ?", values)
        self._conn.commit()
        return self.get(routine_id)

    def delete(self, routine_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def record_run(self, routine_id: str, status: str = "running") -> str:
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO routine_runs (id, routine_id, started_at, status) VALUES (?, ?, ?, ?)",
            (run_id, routine_id, now, status),
        )
        self._conn.commit()
        return run_id

    def finish_run(self, run_id: str, status: str, result: str, routine_id: str):
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE routine_runs SET finished_at = ?, status = ?, result = ? WHERE id = ?",
            (now, status, result, run_id),
        )
        # Update last_run / last_result on the routine
        self._conn.execute(
            "UPDATE routines SET last_run = ?, last_result = ?, updated_at = ? WHERE id = ?",
            (now, result[:500] if result else None, now, routine_id),
        )
        self._conn.commit()

    def recent_runs(self, routine_id: str, limit: int = 10) -> List[dict]:
        rows = self._conn.execute(
            "SELECT * FROM routine_runs WHERE routine_id = ? ORDER BY started_at DESC LIMIT ?",
            (routine_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["enabled"] = bool(d["enabled"])
        if isinstance(d.get("schedule"), str):
            d["schedule"] = json.loads(d["schedule"])
        return d


# ---------------------------------------------------------------------------
# Schedule evaluation
# ---------------------------------------------------------------------------

def _should_run(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if a routine should run given its schedule and last run time."""
    stype = schedule.get("type", "daily")
    time_str = schedule.get("time", "08:00")  # HH:MM in local time

    if stype == "interval":
        minutes = schedule.get("minutes", 60)
        if not last_run:
            return True
        last = datetime.fromisoformat(last_run)
        return (now - last) >= timedelta(minutes=minutes)

    # Time-based schedules: check if we're past the target time and haven't run today
    try:
        target_hour, target_min = int(time_str.split(":")[0]), int(time_str.split(":")[1])
    except (ValueError, IndexError):
        target_hour, target_min = 8, 0

    now_local = now.astimezone()  # Convert to local timezone
    target_today = now_local.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)

    # Haven't reached the target time yet today
    if now_local < target_today:
        return False

    # Already ran after the target time today
    if last_run:
        last = datetime.fromisoformat(last_run)
        if hasattr(last, 'astimezone'):
            last = last.astimezone()
        if last >= target_today:
            return False

    weekday = now_local.weekday()  # 0=Monday

    if stype == "daily":
        return True
    elif stype == "weekdays":
        return weekday < 5
    elif stype == "weekly":
        days = schedule.get("days", [0])  # List of weekday numbers
        return weekday in days

    return False


# ---------------------------------------------------------------------------
# Routine Runner — the scheduler loop
# ---------------------------------------------------------------------------

class RoutineRunner:
    """Background loop that checks and executes scheduled routines."""

    def __init__(self, store: RoutineStore, check_interval: int = 60):
        self._store = store
        self._check_interval = check_interval  # seconds between schedule checks
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"RoutineRunner started (check every {self._check_interval}s)")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("RoutineRunner stopped")

    async def _loop(self):
        while self._running:
            try:
                await self._check_routines()
            except Exception as e:
                logger.error(f"Routine check error: {e}")
            await asyncio.sleep(self._check_interval)

    async def _check_routines(self):
        now = datetime.now(timezone.utc)
        routines = self._store.list()

        for routine in routines:
            if not routine["enabled"]:
                continue
            if _should_run(routine["schedule"], routine["last_run"], now):
                asyncio.create_task(self._execute_routine(routine))

    async def _execute_routine(self, routine: dict):
        """Execute a routine by running its prompt through the agent."""
        routine_id = routine["id"]
        run_id = self._store.record_run(routine_id)
        logger.info(f"Running routine '{routine['name']}': {routine['prompt'][:60]}...")

        try:
            # Import here to avoid circular imports
            from server_state import get_user_session, get_session_agent

            # Create a dedicated session for this routine execution
            session_id = f"routine-{routine_id}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            session = get_user_session(session_id)
            agent = await get_session_agent(session)

            if not agent:
                self._store.finish_run(run_id, "failed", "No agent available (missing API key?)", routine_id)
                logger.warning(f"Routine '{routine['name']}' failed: no agent")
                return

            # Add today's date context
            today = datetime.now().strftime("%A, %B %d, %Y")
            prompt = f"TODAY: {today}\n\n{routine['prompt']}"

            state = await agent.run(prompt)
            result = state.final_response or "(no response)"

            # Save to session for user to review
            session.messages.append({"role": "user", "content": f"[Routine: {routine['name']}] {routine['prompt']}"})
            session.messages.append({"role": "assistant", "content": result})
            session.auto_save()

            self._store.finish_run(run_id, "completed", result, routine_id)
            logger.info(f"Routine '{routine['name']}' completed ({len(result)} chars)")

        except Exception as e:
            self._store.finish_run(run_id, "failed", str(e), routine_id)
            logger.error(f"Routine '{routine['name']}' failed: {e}")

    async def run_now(self, routine_id: str) -> Optional[str]:
        """Manually trigger a routine. Returns the run_id."""
        routine = self._store.get(routine_id)
        if not routine:
            return None
        asyncio.create_task(self._execute_routine(routine))
        return routine_id


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_store: Optional[RoutineStore] = None
_runner: Optional[RoutineRunner] = None


def get_routine_store() -> RoutineStore:
    global _store
    if _store is None:
        _store = RoutineStore()
    return _store


def get_routine_runner() -> RoutineRunner:
    global _runner
    if _runner is None:
        _runner = RoutineRunner(get_routine_store())
    return _runner
