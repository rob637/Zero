"""
Apex Web Server - Beautiful UI prototype

Run with:
    cd apex
    python server.py

Then open http://localhost:8000 in your browser.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.core import Orchestrator, workflow_engine, proactive_scanner
from src.core.llm import create_client_from_env
from src.skills import (
    FileOrganizerSkill, 
    DuplicateFinderSkill, 
    TempCleanerSkill, 
    GmailSkill, 
    DocumentSkill,
    PhotoOrganizerSkill,
    DiskAnalyzerSkill,
)

# Phase 4-5: Intelligence Layer
from intelligence.proactive_monitor import ProactiveMonitor
from intelligence.cross_service import CrossServiceIntelligence
from intelligence.semantic_memory import SemanticMemory
from connectors.devtools import UnifiedDevTools

# Initialize
app = FastAPI(title="Apex", description="Privacy-First Personal AI Assistant")

# CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize orchestrator
orchestrator = Orchestrator()

# Phase 4-5: Intelligence Layer singletons
_proactive_monitor: Optional[ProactiveMonitor] = None
_cross_service_intel: Optional[CrossServiceIntelligence] = None
_semantic_memory: Optional[SemanticMemory] = None
_devtools: Optional[UnifiedDevTools] = None


def get_proactive_monitor() -> ProactiveMonitor:
    """Get or create the ProactiveMonitor singleton."""
    global _proactive_monitor
    if _proactive_monitor is None:
        _proactive_monitor = ProactiveMonitor()
    return _proactive_monitor


def get_cross_service_intel() -> CrossServiceIntelligence:
    """Get or create the CrossServiceIntelligence singleton."""
    global _cross_service_intel, _semantic_memory
    if _cross_service_intel is None:
        if _semantic_memory is None:
            _semantic_memory = SemanticMemory()
        _cross_service_intel = CrossServiceIntelligence(_semantic_memory)
    return _cross_service_intel


def get_devtools() -> UnifiedDevTools:
    """Get or create the UnifiedDevTools singleton."""
    global _devtools
    if _devtools is None:
        _devtools = UnifiedDevTools()
    return _devtools


# Request models
class SubmitRequest(BaseModel):
    request: str


class ChatRequest(BaseModel):
    message: str


class ScanRequest(BaseModel):
    folder: str = ""
    feature: str = "organize"


class ApproveRequest(BaseModel):
    task_id: str
    approved_indices: list[int]


class RejectRequest(BaseModel):
    task_id: str


# Chat system prompt for conversational AI
CHAT_SYSTEM_PROMPT = """You are Apex, a helpful personal AI assistant that lives on the user's PC.

Your capabilities:
1. **File Organization** - Organize messy folders, sort files by type/date, clean up Downloads/Desktop
2. **Duplicate Finder** - Find and remove duplicate files wasting disk space
3. **Temp Cleaner** - Clean temporary files, browser caches, free up space
4. **Gmail Access** - Read and search emails to find travel confirmations, receipts, etc.
5. **Document Creator** - Create documents, itineraries, summaries from collected data
6. **Photo Organizer** - Sort photos by date, separate screenshots, find photo duplicates
7. **Disk Analyzer** - Find what's using your storage, identify large files and space wasters

SPECIAL: Multi-step workflows for complex tasks:
- "travel_itinerary" - Search emails for travel bookings → Create itinerary document
- "pc_cleanup" - Analyze disk → Clean temps → Find duplicates  
- "photo_cleanup" - Organize photos → Find duplicate photos
- "weekly_maintenance" - Clean temps → Organize downloads → Check disk

When detecting intent:
1. For simple single-skill tasks: set "action" to the skill name
2. For compound tasks (multiple steps needed): set "workflow" to the workflow name
3. For conversation only: set both to null

IMPORTANT: Respond with valid JSON:
{
    "response": "Your conversational message to the user",
    "action": "file_organizer" | "duplicate_finder" | "temp_cleaner" | "gmail" | "document" | "photo_organizer" | "disk_analyzer" | null,
    "workflow": "travel_itinerary" | "pc_cleanup" | "photo_cleanup" | "weekly_maintenance" | null,
    "target": "path or folder name if mentioned, or null"
}

Examples:
- "organize my downloads" -> action: "file_organizer", workflow: null
- "create an itinerary from my travel emails" -> action: null, workflow: "travel_itinerary"
- "do a full cleanup of my PC" -> action: null, workflow: "pc_cleanup"
- "my pc is slow" -> action: "temp_cleaner", workflow: null
- "weekly maintenance" -> action: null, workflow: "weekly_maintenance"
- "clean up and organize my photos" -> action: null, workflow: "photo_cleanup"
- "what can you do?" -> action: null, workflow: null (just explain)
"""


# Routes
@app.get("/")
async def root():
    """Serve the UI."""
    return FileResponse(Path(__file__).parent / "ui" / "index.html")


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Main chat endpoint - the AI assistant interface.
    
    This is where natural language becomes action.
    """
    llm = create_client_from_env()
    
    if not llm:
        return JSONResponse({
            "error": "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
            "response": None,
            "plan": None,
            "task_id": None
        })
    
    try:
        # Ask LLM to understand intent
        import json
        
        result = await llm.complete_json(
            system=CHAT_SYSTEM_PROMPT,
            user=req.message
        )
        
        response_text = result.get("response", "I'm not sure how to help with that.")
        action = result.get("action")
        workflow_name = result.get("workflow")
        target = result.get("target")
        
        # Check for multi-step workflow
        if workflow_name:
            try:
                workflow = workflow_engine.create_workflow(workflow_name, {"target": target} if target else {})
                
                # Analyze the first step
                step = await workflow_engine.analyze_step(workflow)
                
                return JSONResponse({
                    "error": None,
                    "response": f"{response_text}\n\nThis is a multi-step task:",
                    "workflow": workflow.to_display_dict(),
                    "workflow_summary": workflow_engine.get_workflow_summary(workflow),
                    "current_step_plan": step.plan.to_display_dict() if step.plan else None,
                    "plan": step.plan.to_display_dict() if step.plan else None,
                    "task_id": None,
                    "workflow_id": workflow.id,
                })
            except ValueError as e:
                # Fall back to single action if workflow template not found
                pass
        
        # Single-skill action
        if action:
            # Build the skill request
            skill_request = req.message
            if target:
                skill_request = f"{req.message} - target: {target}"
            
            task = await orchestrator.submit(skill_request)
            
            if task.error:
                return JSONResponse({
                    "error": None,
                    "response": f"{response_text}\n\nHmm, I ran into an issue: {task.error}",
                    "plan": None,
                    "task_id": None
                })
            
            plan_dict = task.plan.to_display_dict() if task.plan else None
            
            return JSONResponse({
                "error": None,
                "response": response_text,
                "plan": plan_dict,
                "task_id": task.id
            })
        
        # No action needed, just conversation
        return JSONResponse({
            "error": None,
            "response": response_text,
            "plan": None,
            "task_id": None
        })
        
    except Exception as e:
        return JSONResponse({
            "error": str(e),
            "response": "Sorry, I encountered an error. Please try again.",
            "plan": None,
            "task_id": None
        })


@app.post("/submit")
async def submit_request(req: SubmitRequest):
    """Submit a new request for analysis."""
    
    # Check for LLM
    if not create_client_from_env():
        return JSONResponse({
            "error": "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.",
            "task_id": None,
            "plan": None
        })
    
    try:
        task = await orchestrator.submit(req.request)
        
        if task.error:
            return JSONResponse({
                "error": task.error,
                "task_id": task.id,
                "plan": None
            })
        
        # Convert plan to dict for JSON
        plan_dict = task.plan.to_display_dict() if task.plan else None
        
        return JSONResponse({
            "error": None,
            "task_id": task.id,
            "plan": plan_dict
        })
        
    except Exception as e:
        return JSONResponse({
            "error": str(e),
            "task_id": None,
            "plan": None
        })


@app.post("/scan/{feature}")
async def scan_feature(feature: str, req: ScanRequest):
    """Scan using a specific PC Cleanup feature."""
    
    # Check for LLM
    if not create_client_from_env():
        return JSONResponse({
            "error": "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.",
            "task_id": None,
            "plan": None
        })
    
    try:
        # Map feature to natural language request
        feature_requests = {
            "organize": f"Organize the files in {req.folder}",
            "duplicates": f"Find duplicate files in {req.folder}",
            "temp": "Clean up temporary files and cache"
        }
        
        request_text = feature_requests.get(feature, f"Analyze {req.folder}")
        task = await orchestrator.submit(request_text)
        
        if task.error:
            return JSONResponse({
                "error": task.error,
                "task_id": task.id,
                "plan": None
            })
        
        # Convert plan to dict for JSON
        plan_dict = task.plan.to_display_dict() if task.plan else None
        
        return JSONResponse({
            "error": None,
            "task_id": task.id,
            "plan": plan_dict
        })
        
    except Exception as e:
        return JSONResponse({
            "error": str(e),
            "task_id": None,
            "plan": None
        })


@app.post("/approve")
async def approve_request(req: ApproveRequest):
    """Approve and execute selected actions."""
    
    try:
        task = await orchestrator.approve(req.task_id, req.approved_indices)
        
        return JSONResponse({
            "error": task.error,
            "task_id": task.id,
            "result": task.result
        })
        
    except ValueError as e:
        return JSONResponse({
            "error": str(e),
            "task_id": req.task_id,
            "result": None
        })


@app.post("/reject")
async def reject_request(req: RejectRequest):
    """Reject a plan."""
    
    try:
        task = await orchestrator.reject(req.task_id)
        return JSONResponse({"status": "rejected", "task_id": task.id})
    except:
        return JSONResponse({"status": "ok"})


# ============================================
# Proactive Suggestions API
# ============================================

@app.get("/suggestions")
async def get_suggestions():
    """Get pending proactive suggestions."""
    suggestions = proactive_scanner.get_pending_suggestions()
    return JSONResponse({
        "suggestions": [s.to_dict() for s in suggestions],
        "count": len(suggestions),
    })


@app.post("/suggestions/scan")
async def run_proactive_scan():
    """Trigger a proactive scan for suggestions."""
    new_suggestions = await proactive_scanner.run_scan()
    return JSONResponse({
        "new_suggestions": [s.to_dict() for s in new_suggestions],
        "count": len(new_suggestions),
    })


@app.post("/suggestions/{suggestion_id}/dismiss")
async def dismiss_suggestion(suggestion_id: str):
    """Dismiss a suggestion."""
    success = proactive_scanner.dismiss_suggestion(suggestion_id)
    return JSONResponse({"success": success})


@app.post("/suggestions/{suggestion_id}/act")
async def act_on_suggestion(suggestion_id: str):
    """Mark a suggestion as acted on and return its action prompt."""
    suggestions = proactive_scanner.get_pending_suggestions()
    suggestion = next((s for s in suggestions if s.id == suggestion_id), None)
    
    if not suggestion:
        return JSONResponse({"error": "Suggestion not found"}, status_code=404)
    
    proactive_scanner.mark_acted_on(suggestion_id)
    
    return JSONResponse({
        "action_prompt": suggestion.action_prompt,
        "skill_hint": suggestion.skill_hint,
    })


# ============================================
# Workflow API
# ============================================

class WorkflowRequest(BaseModel):
    template: str
    context: dict = {}


class WorkflowStepRequest(BaseModel):
    workflow_id: str
    approved_indices: list[int] | None = None


@app.post("/workflow/create")
async def create_workflow(req: WorkflowRequest):
    """Create a new workflow from a template."""
    try:
        workflow = workflow_engine.create_workflow(req.template, req.context)
        return JSONResponse({
            "workflow": workflow.to_display_dict(),
            "summary": workflow_engine.get_workflow_summary(workflow),
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/workflow/analyze")
async def analyze_workflow_step(req: WorkflowStepRequest):
    """Analyze the current step of a workflow."""
    workflow = workflow_engine.get_workflow(req.workflow_id)
    if not workflow:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    
    step = await workflow_engine.analyze_step(workflow)
    
    return JSONResponse({
        "workflow": workflow.to_display_dict(),
        "current_step": {
            "id": step.id,
            "skill": step.skill_name,
            "description": step.description,
            "status": step.status.value,
            "plan": step.plan.to_display_dict() if step.plan else None,
            "error": step.error,
        },
        "summary": workflow_engine.get_workflow_summary(workflow),
    })


@app.post("/workflow/execute")
async def execute_workflow_step(req: WorkflowStepRequest):
    """Execute the approved current step of a workflow."""
    workflow = workflow_engine.get_workflow(req.workflow_id)
    if not workflow:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    
    step = await workflow_engine.execute_step(workflow, req.approved_indices)
    
    # Advance to next step if successful
    has_next = False
    if step.status.value == "completed":
        has_next = workflow.advance()
    
    return JSONResponse({
        "workflow": workflow.to_display_dict(),
        "executed_step": {
            "id": step.id,
            "status": step.status.value,
            "output": step.output_data,
            "error": step.error,
        },
        "has_next": has_next,
        "completed": workflow.completed,
        "summary": workflow_engine.get_workflow_summary(workflow),
    })


@app.post("/workflow/skip")
async def skip_workflow_step(req: WorkflowStepRequest):
    """Skip the current step of a workflow."""
    workflow = workflow_engine.get_workflow(req.workflow_id)
    if not workflow:
        return JSONResponse({"error": "Workflow not found"}, status_code=404)
    
    workflow_engine.skip_step(workflow)
    has_next = workflow.advance()
    
    return JSONResponse({
        "workflow": workflow.to_display_dict(),
        "has_next": has_next,
        "completed": workflow.completed,
        "summary": workflow_engine.get_workflow_summary(workflow),
    })


@app.get("/workflow/templates")
async def list_workflow_templates():
    """List available workflow templates."""
    from src.core.workflow import WORKFLOW_TEMPLATES
    
    templates = [
        {
            "name": name,
            "display_name": template["name"],
            "description": template["description"],
            "triggers": template["triggers"],
            "step_count": len(template["steps"]),
        }
        for name, template in WORKFLOW_TEMPLATES.items()
    ]
    
    return JSONResponse({"templates": templates})


# ============================================
# Intelligence API (Phase 4-5)
# ============================================

@app.get("/intelligence/alerts")
async def get_alerts():
    """Get proactive alerts from the monitoring system."""
    monitor = get_proactive_monitor()
    alerts = monitor.get_pending_alerts()
    
    return JSONResponse({
        "alerts": [a.to_dict() for a in alerts],
        "count": len(alerts),
        "stats": monitor.get_stats(),
    })


@app.post("/intelligence/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert."""
    monitor = get_proactive_monitor()
    success = monitor.acknowledge_alert(alert_id)
    return JSONResponse({"success": success, "alert_id": alert_id})


@app.post("/intelligence/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str):
    """Dismiss an alert."""
    monitor = get_proactive_monitor()
    success = monitor.dismiss_alert(alert_id)
    return JSONResponse({"success": success, "alert_id": alert_id})


@app.get("/intelligence/briefing")
async def get_briefing():
    """Get a morning briefing with cross-service intelligence."""
    intel = get_cross_service_intel()
    
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


@app.get("/intelligence/devtools")
async def get_devtools_summary():
    """Get unified development tools summary (GitHub + Jira)."""
    devtools = get_devtools()
    
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


@app.post("/intelligence/devtools/connect/github")
async def connect_github():
    """Connect GitHub to DevTools."""
    from connectors.github import GitHubConnector
    
    devtools = get_devtools()
    monitor = get_proactive_monitor()
    
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


@app.post("/intelligence/devtools/connect/jira")
async def connect_jira():
    """Connect Jira to DevTools."""
    from connectors.jira import JiraConnector
    
    devtools = get_devtools()
    monitor = get_proactive_monitor()
    
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


@app.post("/intelligence/devtools/connect/slack")
async def connect_slack():
    """Connect Slack to DevTools."""
    from connectors.slack import SlackConnector
    
    monitor = get_proactive_monitor()
    
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


@app.post("/intelligence/monitor/start")
async def start_monitoring():
    """Start the proactive monitoring loop."""
    monitor = get_proactive_monitor()
    await monitor.start()
    return JSONResponse({
        "running": monitor.is_running,
        "stats": monitor.get_stats(),
    })


@app.post("/intelligence/monitor/stop")
async def stop_monitoring():
    """Stop the proactive monitoring loop."""
    monitor = get_proactive_monitor()
    await monitor.stop()
    return JSONResponse({
        "running": monitor.is_running,
        "stats": monitor.get_stats(),
    })


@app.get("/intelligence/monitor/status")
async def monitor_status():
    """Get monitoring status."""
    monitor = get_proactive_monitor()
    return JSONResponse({
        "running": monitor.is_running,
        "paused": monitor._paused,
        "stats": monitor.get_stats(),
        "connected_services": list(monitor._services.keys()),
    })


# ============================================
# Integration Platform API
# ============================================

from src.integrations import (
    CredentialManager,
    get_credential_manager,
    EventBus,
    get_event_bus,
    ContextEngine,
    get_context_engine,
)
from src.connectors import (
    get_gmail_connector,
    get_calendar_connector,
    get_drive_connector,
)


class OAuthInitRequest(BaseModel):
    provider: str  # google, microsoft, notion, etc.
    service: str   # gmail, calendar, drive, etc.
    client_id: str
    client_secret: str
    scopes: list[str] | None = None


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


@app.get("/integrations/services")
async def list_connected_services():
    """List all connected services and their status."""
    cred_manager = get_credential_manager()
    services = cred_manager.list_services()
    
    # Add connector status
    for service in services:
        service["connected"] = service.get("has_access_token", False)
    
    return JSONResponse({
        "services": services,
        "available_providers": ["google", "microsoft", "notion", "slack", "github"],
    })


@app.post("/integrations/oauth/init")
async def init_oauth_flow(req: OAuthInitRequest):
    """
    Initialize OAuth flow for a service.
    
    Returns an authorization URL to redirect the user to.
    """
    cred_manager = get_credential_manager()
    
    try:
        auth_url = cred_manager.get_oauth_url(
            provider=req.provider,
            service=req.service,
            client_id=req.client_id,
            client_secret=req.client_secret,
            scopes=req.scopes,
        )
        
        return JSONResponse({
            "auth_url": auth_url,
            "message": f"Redirect user to auth_url to authorize {req.service}",
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/oauth/callback")
async def oauth_callback(code: str, state: str):
    """
    OAuth callback endpoint.
    
    This is where the OAuth provider redirects after user authorization.
    """
    cred_manager = get_credential_manager()
    
    try:
        creds = await cred_manager.handle_oauth_callback(code, state)
        
        # Return success page
        return FileResponse(Path(__file__).parent / "ui" / "oauth_success.html")
        
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/integrations/oauth/callback")
async def oauth_callback_post(req: OAuthCallbackRequest):
    """Handle OAuth callback via POST (for testing)."""
    cred_manager = get_credential_manager()
    
    try:
        creds = await cred_manager.handle_oauth_callback(req.code, req.state)
        return JSONResponse({
            "success": True,
            "service": creds.service,
            "message": f"Successfully authenticated {creds.service}",
        })
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.delete("/integrations/{service}")
async def disconnect_service(service: str):
    """Disconnect a service (remove stored credentials)."""
    cred_manager = get_credential_manager()
    success = cred_manager.delete_credentials(service)
    return JSONResponse({
        "success": success,
        "message": f"Disconnected {service}" if success else f"Service {service} not found",
    })


# --- Gmail API ---

@app.get("/integrations/gmail/messages")
async def list_gmail_messages(
    query: str = "",
    max_results: int = 20,
    include_body: bool = False,
):
    """List Gmail messages."""
    connector = get_gmail_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Gmail not connected. Please authenticate first."}, status_code=401)
    
    try:
        emails = await connector.list_messages(
            query=query,
            max_results=max_results,
            include_body=include_body,
        )
        return JSONResponse({
            "messages": [e.to_dict() for e in emails],
            "count": len(emails),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/integrations/gmail/unread")
async def get_gmail_unread():
    """Get unread email count and recent unread messages."""
    connector = get_gmail_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Gmail not connected"}, status_code=401)
    
    try:
        count = await connector.get_unread_count()
        recent = await connector.list_messages(query="is:unread", max_results=5, include_body=False)
        
        return JSONResponse({
            "unread_count": count,
            "recent_unread": [e.to_dict() for e in recent],
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


class SendEmailRequest(BaseModel):
    to: list[str]
    subject: str
    body: str
    cc: list[str] | None = None


@app.post("/integrations/gmail/send")
async def send_gmail(req: SendEmailRequest):
    """Send an email via Gmail."""
    connector = get_gmail_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Gmail not connected"}, status_code=401)
    
    try:
        result = await connector.send_email(
            to=req.to,
            subject=req.subject,
            body=req.body,
            cc=req.cc,
        )
        return JSONResponse({
            "success": True,
            "message_id": result.get("id"),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Calendar API ---

@app.get("/integrations/calendar/events")
async def list_calendar_events(
    calendar_id: str = "primary",
    days_ahead: int = 7,
    max_results: int = 50,
):
    """List upcoming calendar events."""
    connector = get_calendar_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Calendar not connected"}, status_code=401)
    
    try:
        from datetime import datetime, timedelta
        time_max = datetime.utcnow() + timedelta(days=days_ahead)
        
        events = await connector.list_events(
            calendar_id=calendar_id,
            time_max=time_max,
            max_results=max_results,
        )
        return JSONResponse({
            "events": [e.to_dict() for e in events],
            "count": len(events),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/integrations/calendar/today")
async def get_today_events():
    """Get today's calendar events."""
    connector = get_calendar_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Calendar not connected"}, status_code=401)
    
    try:
        events = await connector.get_today_events()
        next_event = await connector.get_next_event()
        
        return JSONResponse({
            "today_events": [e.to_dict() for e in events],
            "next_event": next_event.to_dict() if next_event else None,
            "count": len(events),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


class CreateEventRequest(BaseModel):
    summary: str
    start: str  # ISO format
    end: str    # ISO format
    description: str = ""
    location: str = ""
    attendees: list[str] | None = None


@app.post("/integrations/calendar/events")
async def create_calendar_event(req: CreateEventRequest):
    """Create a new calendar event."""
    connector = get_calendar_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Calendar not connected"}, status_code=401)
    
    try:
        from datetime import datetime
        event = await connector.create_event(
            summary=req.summary,
            start=datetime.fromisoformat(req.start),
            end=datetime.fromisoformat(req.end),
            description=req.description,
            location=req.location,
            attendees=req.attendees,
        )
        return JSONResponse({
            "success": True,
            "event": event.to_dict(),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Drive API ---

@app.get("/integrations/drive/files")
async def list_drive_files(
    query: str = "",
    folder_id: str | None = None,
    max_results: int = 50,
):
    """List Google Drive files."""
    connector = get_drive_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Drive not connected"}, status_code=401)
    
    try:
        files = await connector.list_files(
            query=query or None,
            folder_id=folder_id,
            max_results=max_results,
        )
        return JSONResponse({
            "files": [f.to_dict() for f in files],
            "count": len(files),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


class CreateFileRequest(BaseModel):
    name: str
    content: str
    mime_type: str = "text/plain"
    folder_id: str | None = None


@app.post("/integrations/drive/files")
async def create_drive_file(req: CreateFileRequest):
    """Create a new file in Google Drive."""
    connector = get_drive_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Drive not connected"}, status_code=401)
    
    try:
        file = await connector.create_file(
            name=req.name,
            content=req.content,
            mime_type=req.mime_type,
            folder_id=req.folder_id,
        )
        return JSONResponse({
            "success": True,
            "file": file.to_dict(),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/integrations/drive/search")
async def search_drive(query: str, max_results: int = 20):
    """Search Google Drive."""
    connector = get_drive_connector()
    
    if not connector.is_connected():
        return JSONResponse({"error": "Drive not connected"}, status_code=401)
    
    try:
        files = await connector.search(query, max_results)
        return JSONResponse({
            "files": [f.to_dict() for f in files],
            "count": len(files),
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# --- Context Engine API ---

@app.get("/integrations/context/stats")
async def get_context_stats():
    """Get context engine statistics."""
    context_engine = get_context_engine()
    return JSONResponse(context_engine.get_stats())


@app.get("/integrations/context/entities")
async def search_entities(
    query: str = "",
    entity_type: str | None = None,
    limit: int = 20,
):
    """Search entities in the context graph."""
    context_engine = get_context_engine()
    
    if not query:
        # Return most interacted entities
        entities = context_engine.get_most_interacted_entities(limit)
    else:
        from src.integrations.context_engine import EntityType
        etype = EntityType(entity_type) if entity_type else None
        entities = context_engine.search_entities(query, etype, limit)
    
    return JSONResponse({
        "entities": [e.to_dict() for e in entities],
        "count": len(entities),
    })


# --- Event Bus API ---

@app.get("/integrations/events")
async def get_recent_events(
    service: str | None = None,
    limit: int = 50,
):
    """Get recent events from the event bus."""
    event_bus = get_event_bus()
    events = event_bus.get_history(service=service, limit=limit)
    
    return JSONResponse({
        "events": [e.to_dict() for e in events],
        "count": len(events),
        "stats": event_bus.get_stats(),
    })


# ============================================================
#  BRAIN ENDPOINTS - The Cognitive System
# ============================================================

# Brain instance (singleton)
_brain = None

async def get_brain():
    """Get or create the unified brain instance."""
    global _brain
    if _brain is None:
        from src.brain import create_brain
        
        # Create brain with storage in user's home
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        _brain = create_brain(
            storage_path=str(Path.home() / ".apex"),
            llm_api_key=api_key,
        )
        await _brain.initialize()
    return _brain


class BrainThinkRequest(BaseModel):
    input: str
    context: dict = {}


class BrainRememberRequest(BaseModel):
    content: str
    tags: list[str] = []


class BrainRecallRequest(BaseModel):
    query: str
    limit: int = 5


class BrainAnticipateRequest(BaseModel):
    what: str
    when: str = None  # ISO format datetime


@app.get("/brain/state")
async def brain_state():
    """Get current brain state."""
    brain = await get_brain()
    return JSONResponse(brain.get_state())


@app.post("/brain/wake")
async def brain_wake():
    """Wake up the brain - start consciousness loop."""
    brain = await get_brain()
    await brain.wake()
    return JSONResponse({"status": "awake", "state": brain.get_state()})


@app.post("/brain/sleep")
async def brain_sleep():
    """Put the brain to sleep - stop consciousness loop."""
    brain = await get_brain()
    await brain.sleep()
    return JSONResponse({"status": "asleep", "state": brain.get_state()})


@app.post("/brain/think")
async def brain_think(request: BrainThinkRequest):
    """Process input through the brain and get a thoughtful response."""
    brain = await get_brain()
    
    # Wake if not awake
    if not brain._awake:
        await brain.wake()
    
    response = await brain.think(request.input, request.context or None)
    
    return JSONResponse({
        "response": response,
        "state": brain.get_state(),
    })


@app.post("/brain/remember")
async def brain_remember(request: BrainRememberRequest):
    """Store something in the brain's long-term memory."""
    brain = await get_brain()
    memory_id = await brain.remember(request.content, request.tags or None)
    
    return JSONResponse({
        "memory_id": memory_id,
        "status": "stored",
    })


@app.post("/brain/recall")
async def brain_recall(request: BrainRecallRequest):
    """Recall memories related to a query."""
    brain = await get_brain()
    memories = await brain.recall(request.query, request.limit)
    
    return JSONResponse({
        "memories": memories,
        "count": len(memories),
    })


@app.post("/brain/anticipate")
async def brain_anticipate(request: BrainAnticipateRequest):
    """Set up an anticipation for something."""
    brain = await get_brain()
    
    when = None
    if request.when:
        from datetime import datetime
        when = datetime.fromisoformat(request.when)
    
    brain.anticipate(request.what, when)
    
    return JSONResponse({
        "status": "anticipating",
        "what": request.what,
        "anticipations": brain.get_anticipations(),
    })


@app.get("/brain/stream")
async def brain_stream(limit: int = 10):
    """Get recent moments from the consciousness stream."""
    brain = await get_brain()
    stream = brain.get_consciousness_stream(limit)
    
    return JSONResponse({
        "stream": stream,
        "count": len(stream),
    })


@app.get("/brain/intentions")
async def brain_intentions():
    """Get current intentions."""
    brain = await get_brain()
    intentions = brain.get_intentions()
    
    return JSONResponse({
        "intentions": intentions,
        "count": len(intentions),
    })


@app.get("/brain/capabilities")
async def brain_capabilities():
    """Get all available capabilities from connected services."""
    brain = await get_brain()
    
    return JSONResponse({
        "capabilities": brain.get_capabilities(),
        "services": brain.get_connected_services(),
    })


@app.post("/brain/connect/{service}")
async def brain_connect_service(service: str):
    """Connect a service to the brain."""
    brain = await get_brain()
    
    # Get the appropriate connector
    if service == "gmail":
        from src.connectors.google import GmailConnector
        cred_manager = get_credential_manager()
        token = cred_manager.get_access_token("gmail")
        if not token:
            raise HTTPException(status_code=400, detail="Gmail not authenticated")
        connector = GmailConnector(token)
        success = brain.connect_service("gmail", connector)
    elif service == "calendar":
        from src.connectors.google import GoogleCalendarConnector
        cred_manager = get_credential_manager()
        token = cred_manager.get_access_token("google_calendar")
        if not token:
            raise HTTPException(status_code=400, detail="Calendar not authenticated")
        connector = GoogleCalendarConnector(token)
        success = brain.connect_service("calendar", connector)
    elif service == "drive":
        from src.connectors.google import GoogleDriveConnector
        cred_manager = get_credential_manager()
        token = cred_manager.get_access_token("google_drive")
        if not token:
            raise HTTPException(status_code=400, detail="Drive not authenticated")
        connector = GoogleDriveConnector(token)
        success = brain.connect_service("drive", connector)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")
    
    return JSONResponse({
        "success": success,
        "service": service,
        "services": brain.get_connected_services(),
    })


@app.get("/health")
async def health():
    """Health check."""
    cred_manager = get_credential_manager()
    services = cred_manager.list_services()
    
    # Check brain status
    brain_status = "not_initialized"
    if _brain:
        brain_status = "awake" if _brain._awake else "initialized"
    
    # Check connected services 
    monitor = get_proactive_monitor()
    devtools = get_devtools()
    
    service_status = {
        "google": any(s.get("name") == "google" and s.get("has_access_token") for s in services),
        "microsoft": any(s.get("name") == "microsoft" and s.get("has_access_token") for s in services),
        "github": "github" in devtools.providers,
        "jira": "jira" in devtools.providers,
        "slack": "slack" in [svc for svc in monitor._services.keys()] if hasattr(monitor, '_services') else False,
    }
    
    return {
        "status": "ok",
        "llm_configured": create_client_from_env() is not None,
        "connected_services": len([s for s in services if s.get("has_access_token")]),
        "brain": brain_status,
        "services": service_status,
    }


# Run with uvicorn
if __name__ == "__main__":
    import uvicorn
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                       APEX WEB UI                             ║
║           Privacy-First Personal AI Assistant                 ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        print("⚠️  No LLM API key found!")
        print("   Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.")
        print()
    else:
        print("✅ LLM API key configured")
    
    print("\n🌐 Opening http://localhost:8000 ...\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
