"""
Nudge API routes — CRUD for AI-generated proactive nudges.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from nudge_engine import get_nudge_store, get_nudge_engine

router = APIRouter(prefix="/api/nudges", tags=["nudges"])


@router.get("")
async def list_nudges():
    """Get active nudges (non-dismissed, not expired)."""
    store = get_nudge_store()
    nudges = store.get_active(limit=20)
    engine = get_nudge_engine()
    return {
        "nudges": [n.to_dict() for n in nudges],
        "count": len(nudges),
        "engine": engine.get_stats(),
    }


@router.post("/{nudge_id}/dismiss")
async def dismiss_nudge(nudge_id: str):
    """Dismiss a nudge."""
    store = get_nudge_store()
    success = store.dismiss(nudge_id)
    return {"success": success, "nudge_id": nudge_id}


@router.post("/{nudge_id}/act")
async def act_on_nudge(nudge_id: str):
    """Mark a nudge as acted on (also dismisses it)."""
    store = get_nudge_store()
    success = store.mark_acted(nudge_id)
    return {"success": success, "nudge_id": nudge_id}


@router.post("/generate")
async def generate_now():
    """Manually trigger a nudge generation cycle."""
    engine = get_nudge_engine()
    new_nudges = await engine.run_once()
    return {
        "generated": len(new_nudges),
        "nudges": [n.to_dict() for n in new_nudges],
    }
