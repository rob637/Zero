"""
Routines API — CRUD + manual trigger for scheduled routines.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from routines import get_routine_store, get_routine_runner

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/routines", tags=["routines"])


class RoutineCreate(BaseModel):
    name: str
    prompt: str
    schedule: dict  # {"type": "daily", "time": "08:00"} etc.


class RoutineUpdate(BaseModel):
    name: Optional[str] = None
    prompt: Optional[str] = None
    schedule: Optional[dict] = None
    enabled: Optional[bool] = None


@router.get("")
async def list_routines():
    """List all routines."""
    store = get_routine_store()
    return store.list()


@router.post("")
async def create_routine(req: RoutineCreate):
    """Create a new routine."""
    if not req.name.strip():
        raise HTTPException(400, "Name is required")
    if not req.prompt.strip():
        raise HTTPException(400, "Prompt is required")

    stype = req.schedule.get("type", "daily")
    if stype not in ("daily", "weekdays", "weekly", "interval"):
        raise HTTPException(400, f"Invalid schedule type: {stype}")

    store = get_routine_store()
    routine = store.create(req.name.strip(), req.prompt.strip(), req.schedule)
    logger.info(f"Created routine '{routine['name']}' ({routine['id'][:8]}...)")
    return routine


@router.get("/{routine_id}")
async def get_routine(routine_id: str):
    """Get a single routine with recent runs."""
    store = get_routine_store()
    routine = store.get(routine_id)
    if not routine:
        raise HTTPException(404, "Routine not found")
    routine["recent_runs"] = store.recent_runs(routine_id, limit=5)
    return routine


@router.put("/{routine_id}")
async def update_routine(routine_id: str, req: RoutineUpdate):
    """Update routine fields."""
    store = get_routine_store()
    updates = req.model_dump(exclude_none=True)
    routine = store.update(routine_id, **updates)
    if not routine:
        raise HTTPException(404, "Routine not found")
    logger.info(f"Updated routine '{routine['name']}' ({routine_id[:8]}...)")
    return routine


@router.delete("/{routine_id}")
async def delete_routine(routine_id: str):
    """Delete a routine."""
    store = get_routine_store()
    if not store.delete(routine_id):
        raise HTTPException(404, "Routine not found")
    logger.info(f"Deleted routine {routine_id[:8]}...")
    return {"deleted": True}


@router.post("/{routine_id}/run")
async def run_routine(routine_id: str):
    """Manually trigger a routine now."""
    runner = get_routine_runner()
    store = get_routine_store()
    routine = store.get(routine_id)
    if not routine:
        raise HTTPException(404, "Routine not found")
    await runner.run_now(routine_id)
    logger.info(f"Manually triggered routine '{routine['name']}'")
    return {"triggered": True, "routine_id": routine_id}


@router.post("/{routine_id}/toggle")
async def toggle_routine(routine_id: str):
    """Toggle a routine enabled/disabled."""
    store = get_routine_store()
    routine = store.get(routine_id)
    if not routine:
        raise HTTPException(404, "Routine not found")
    updated = store.update(routine_id, enabled=not routine["enabled"])
    logger.info(f"Toggled routine '{updated['name']}' → {'enabled' if updated['enabled'] else 'disabled'}")
    return updated
