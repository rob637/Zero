"""
Telic Intelligence, Privacy & Control Routes

Handles proactive alerts, briefings, patterns, semantic memory,
audit logging, trust levels, and action history/undo.
"""
import os
from typing import Optional
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import server_state as ss

router = APIRouter()


@router.get("/intelligence/alerts")
async def get_alerts():
    """Get proactive alerts and suggestions from the intelligence layer."""
    monitor = ss.get_proactive_monitor()
    alerts = monitor.get_pending_alerts()
    
    # Also get intelligence suggestions
    suggestions = []
    try:
        hub = ss.get_intelligence_hub()
        raw_suggestions = await hub.get_suggestions(max_suggestions=5)
        suggestions = [s.to_dict() for s in raw_suggestions] if raw_suggestions else []
    except Exception:
        pass
    
    return JSONResponse({
        "alerts": [a.to_dict() for a in alerts],
        "suggestions": suggestions,
        "count": len(alerts) + len(suggestions),
        "stats": monitor.get_stats(),
    })


@router.post("/intelligence/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert."""
    monitor = ss.get_proactive_monitor()
    success = monitor.acknowledge_alert(alert_id)
    return JSONResponse({"success": success, "alert_id": alert_id})


@router.post("/intelligence/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str):
    """Dismiss an alert."""
    monitor = ss.get_proactive_monitor()
    success = monitor.dismiss_alert(alert_id)
    return JSONResponse({"success": success, "alert_id": alert_id})


@router.get("/intelligence/briefing")
async def get_briefing():
    """Get a morning briefing with cross-service intelligence."""
    intel = ss.get_cross_service_intel()
    
    try:
        briefing = await intel.morning_briefing()
        return JSONResponse({
            "briefing": briefing,
            "generated_at": intel._memory._now().isoformat() if intel._memory else None,
        })
    except Exception as e:
        return JSONResponse({
            "error": str(e),
            "briefing": None,
        })


@router.get("/intelligence/devtools")
async def get_devtools_summary():
    """Get unified development tools summary (GitHub + Jira)."""
    devtools = ss.get_devtools()
    
    if not devtools.providers:
        return JSONResponse({
            "error": "No DevTools providers connected. Connect GitHub or Jira first.",
            "summary": None,
            "providers": [],
        })
    
    try:
        summary = await devtools.get_work_summary()
        return JSONResponse({
            "summary": summary,
            "providers": devtools.providers,
        })
    except Exception as e:
        return JSONResponse({
            "error": str(e),
            "summary": None,
            "providers": devtools.providers,
        })


@router.post("/intelligence/devtools/connect/github")
async def connect_github():
    """Connect GitHub to DevTools."""
    from connectors.github import GitHubConnector
    
    devtools = ss.get_devtools()
    monitor = ss.get_proactive_monitor()
    
    connector = GitHubConnector()
    connected = await connector.connect()
    
    if connected:
        devtools.add_github(connector)
        monitor.connect_service("github", connector)
        return JSONResponse({
            "success": True,
            "user": connector.current_user.login if connector.current_user else None,
            "providers": devtools.providers,
        })
    else:
        return JSONResponse({
            "success": False,
            "error": "Failed to connect to GitHub. Set GITHUB_TOKEN or install gh CLI.",
            "providers": devtools.providers,
        })


@router.post("/intelligence/devtools/connect/jira")
async def connect_jira():
    """Connect Jira to DevTools."""
    from connectors.jira import JiraConnector
    
    devtools = ss.get_devtools()
    monitor = ss.get_proactive_monitor()
    
    connector = JiraConnector()
    connected = await connector.connect()
    
    if connected:
        devtools.add_jira(connector)
        monitor.connect_service("jira", connector)
        return JSONResponse({
            "success": True,
            "user": connector.current_user.display_name if connector.current_user else None,
            "providers": devtools.providers,
        })
    else:
        return JSONResponse({
            "success": False,
            "error": "Failed to connect to Jira. Set JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN.",
            "providers": devtools.providers,
        })


@router.post("/intelligence/devtools/connect/slack")
async def connect_slack():
    """Connect Slack to DevTools."""
    from connectors.slack import SlackConnector
    
    monitor = ss.get_proactive_monitor()
    
    connector = SlackConnector()
    connected = await connector.connect()
    
    if connected:
        monitor.connect_service("slack", connector)
        return JSONResponse({
            "success": True,
            "user": connector.current_user.name if connector.current_user else None,
            "team": connector.team.get("name") if connector.team else None,
        })
    else:
        return JSONResponse({
            "success": False,
            "error": "Failed to connect to Slack. Set SLACK_BOT_TOKEN environment variable.",
        })


@router.post("/intelligence/monitor/start")
async def start_monitoring():
    """Start the proactive monitoring loop."""
    monitor = ss.get_proactive_monitor()
    await monitor.start()
    return JSONResponse({
        "running": monitor._state.value == "running",
        "stats": monitor.get_stats(),
    })


@router.post("/intelligence/monitor/stop")
async def stop_monitoring():
    """Stop the proactive monitoring loop."""
    monitor = ss.get_proactive_monitor()
    await monitor.stop()
    return JSONResponse({
        "running": monitor._state.value == "running",
        "stats": monitor.get_stats(),
    })


@router.get("/intelligence/monitor/status")
async def monitor_status():
    """Get monitoring status."""
    monitor = ss.get_proactive_monitor()
    return JSONResponse({
        "running": monitor._state.value == "running",
        "paused": monitor._state.value == "paused",
        "stats": monitor.get_stats(),
        "connected_services": list(monitor._service_adapters.keys()),
    })


@router.get("/intelligence/stats")
async def intelligence_stats():
    """Get comprehensive intelligence layer statistics."""
    hub = ss.get_intelligence_hub()
    return JSONResponse(hub.get_stats())


@router.get("/intelligence/memory")
async def intelligence_memory(query: str = "", entity: str = ""):
    """Query semantic memory."""
    hub = ss.get_intelligence_hub()
    if entity:
        facts = await hub.recall_about(entity)
        return JSONResponse({
            "entity": entity,
            "facts": [f.to_dict() for f in facts] if facts else [],
        })
    elif query:
        facts = await hub.recall(query, limit=10)
        return JSONResponse({
            "query": query,
            "facts": [f.to_dict() for f, _score in facts] if facts else [],
        })
    else:
        stats = hub._memory.get_stats()
        return JSONResponse({"stats": stats})


@router.get("/intelligence/patterns")
async def intelligence_patterns():
    """Get detected behavioral patterns."""
    hub = ss.get_intelligence_hub()
    patterns = await hub.get_patterns()
    return JSONResponse({
        "patterns": [p.to_dict() for p in patterns] if patterns else [],
        "count": len(patterns) if patterns else 0,
    })



@router.get("/privacy/audit")
async def get_audit_log(limit: int = 50):
    """
    Get recent external data transmissions.
    
    Every time data is sent to an LLM, it's logged here.
    Users can review exactly what was sent externally.
    """
    records = ss.audit_logger.get_transmissions(limit=limit)
    return JSONResponse({
        "transmissions": [r.to_dict() for r in records],
        "count": len(records),
    })


@router.get("/privacy/audit/stats")
async def get_audit_stats():
    """
    Get transmission statistics for the last 24 hours.
    
    Shows: total calls, bytes sent, PII detected, destinations used.
    """
    stats = ss.audit_logger.get_stats()
    return JSONResponse(stats)


@router.get("/privacy/audit/today")
async def get_audit_today():
    """
    Get human-readable summary of today's transmissions.
    """
    summary = ss.audit_logger.get_today_summary()
    return JSONResponse({
        "summary": summary,
    })


@router.post("/privacy/redact")
async def test_redaction(text: str):
    """
    Test PII redaction on a piece of text.
    
    Use this to see what would be redacted before sending to LLM.
    """
    result = ss.redaction_engine.redact(text)
    return JSONResponse({
        "original_length": len(text),
        "redacted_text": result.redacted_text,
        "redaction_count": result.redaction_count,
        "had_pii": result.had_pii,
        "redactions": result.redactions,
    })


@router.get("/privacy/trust")
async def get_trust_levels():
    """
    Get all trust level settings.
    
    Shows which actions require approval vs auto-approve.
    """
    levels = ss.trust_manager.get_all_levels()
    return JSONResponse({
        "trust_levels": levels,
        "legend": {
            "always_ask": "🔴 Always require explicit approval",
            "ask_once": "🟡 Ask once, offer to remember pattern",
            "auto_approve": "🟢 Execute without asking",
        }
    })


@router.post("/privacy/trust/{action_type}")
async def set_trust_level(action_type: str, level: str):
    """
    Set trust level for an action type.
    
    Levels: always_ask, ask_once, auto_approve
    """
    try:
        trust_level = ss.TrustLevel(level)
        ss.trust_manager.set_trust_level(action_type, trust_level)
        return JSONResponse({
            "success": True,
            "action_type": action_type,
            "level": level,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/privacy/pending")
async def get_pending_actions():
    """
    Get all actions awaiting approval.
    
    These are actions that need user confirmation before executing.
    """
    pending = ss.approval_gateway.get_pending()
    return JSONResponse({
        "pending": [a.to_dict() for a in pending],
        "count": len(pending),
    })


@router.post("/privacy/approve/{action_id}")
async def approve_action(action_id: str):
    """
    Approve a pending action.
    
    The action will be executed immediately.
    """
    try:
        result = await ss.approval_gateway.approve(action_id)
        return JSONResponse({
            "success": True,
            "action_id": action_id,
            "status": result.status.value,
            "result": result.result,
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/privacy/reject/{action_id}")
async def reject_action(action_id: str, reason: str = None):
    """
    Reject a pending action.
    
    The action will not be executed.
    """
    try:
        result = await ss.approval_gateway.reject(action_id, reason=reason)
        return JSONResponse({
            "success": True,
            "action_id": action_id,
            "status": result.status.value,
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =============================================================================
# PHASE 7 SPRINT 4: CONTROL LAYER ENDPOINTS
# =============================================================================

class ApproveActionRequest(BaseModel):
    action_id: str
    modifications: Optional[Dict[str, Any]] = None
    remember_pattern: bool = False
    pattern_context: Optional[Dict[str, Any]] = None


class UndoActionRequest(BaseModel):
    action_id: str


@router.get("/control/history")
async def get_action_history(limit: int = 50, category: str = None, status: str = None):
    """
    Get action history with optional filtering.
    
    Shows all actions that have been recorded, including their status.
    """
    actions = ss.action_history.get_recent(limit=limit)
    
    # Optional filtering
    if category:
        actions = [a for a in actions if a.category.value == category]
    if status:
        actions = [a for a in actions if a.status.value == status]
    
    return JSONResponse({
        "actions": [a.to_dict() for a in actions],
        "count": len(actions),
    })


@router.get("/control/history/{action_id}")
async def get_action_detail(action_id: str):
    """
    Get details of a specific action.
    """
    record = ss.action_history.get_by_id(action_id)
    if not record:
        raise HTTPException(status_code=404, detail="Action not found")
    
    return JSONResponse(record.to_dict())


@router.post("/control/approve")
async def approve_control_action(request: ApproveActionRequest):
    """
    Approve an action via the control layer.
    
    This creates a checkpoint for undo, executes the action, and logs it.
    Supports trust level learning via remember_pattern flag.
    """
    action_id = request.action_id
    
    try:
        # Get the action from approval gateway
        result = await ss.approval_gateway.approve(
            action_id,
            modifications=request.modifications,
            remember_pattern=request.remember_pattern,
            pattern_context=request.pattern_context,
        )
        
        # Mark completed in action history
        ss.action_history.mark_completed(action_id, result=result.result)
        
        return JSONResponse({
            "success": True,
            "action_id": action_id,
            "result": result.result,
        })
    except ValueError as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=400)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=500)


@router.post("/control/reject")
async def reject_control_action(request: ApproveActionRequest):
    """
    Reject an action via the control layer.
    """
    action_id = request.action_id
    
    try:
        result = await ss.approval_gateway.reject(action_id)
        return JSONResponse({
            "success": True,
            "action_id": action_id,
        })
    except ValueError as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=400)


@router.post("/control/undo")
async def undo_action(request: UndoActionRequest):
    """
    Undo a completed action.
    
    Only works for actions that have checkpoints and are within the undo window.
    """
    action_id = request.action_id
    
    try:
        # Get action record
        record = ss.action_history.get_by_id(action_id)
        if not record:
            return JSONResponse({
                "success": False,
                "error": "Action not found",
            }, status_code=404)
        
        if not record.is_undoable:
            return JSONResponse({
                "success": False,
                "error": "Action is not undoable",
            }, status_code=400)
        
        # Try to undo via undo manager
        checkpoint_id = record.payload.get("checkpoint_id")
        if checkpoint_id:
            result = await ss.undo_manager.undo(checkpoint_id)
            if result.status.value == "completed":
                ss.action_history.mark_undone(action_id)
                return JSONResponse({
                    "success": True,
                    "action_id": action_id,
                    "message": "Action undone successfully",
                })
            else:
                return JSONResponse({
                    "success": False,
                    "error": f"Undo failed: {result.error}",
                }, status_code=500)
        else:
            # No checkpoint, just mark as undone
            ss.action_history.mark_undone(action_id)
            return JSONResponse({
                "success": True,
                "action_id": action_id,
                "message": "Action marked as undone (no checkpoint to restore)",
            })
            
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=500)


@router.get("/control/checkpoints")
async def get_checkpoints(limit: int = 20):
    """
    Get recent undo checkpoints.
    """
    checkpoints = ss.undo_manager.get_checkpoints(limit=limit)
    return JSONResponse({
        "checkpoints": [c.to_dict() for c in checkpoints],
        "count": len(checkpoints),
    })

