"""
Telic Web Server - AI Operating System

Run with:
    cd apex
    python server.py

Then open http://localhost:8000 in your browser.
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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

# Telic Engine - the REAL engine with all primitives
from apex_engine import Apex as TelicEngine

# Phase 7: Privacy & Control Layer
from src.privacy import (
    AuditLogger, audit_logger,
    RedactionEngine, redaction_engine,
    SecureLLMClient, create_secure_client_from_env,
)
from src.control import (
    TrustLevel, TrustLevelManager, trust_manager,
    ApprovalGateway, approval_gateway,
    ActionHistoryDB, action_history,
    UndoManager, undo_manager,
)

# Phase 4-5: Intelligence Layer
from intelligence.proactive_monitor import ProactiveMonitor
from intelligence.cross_service import CrossServiceIntelligence
from intelligence.semantic_memory import SemanticMemory
from connectors.devtools import UnifiedDevTools

# Google Calendar connector (real API)
try:
    from connectors.google_auth import GoogleAuth, get_google_auth
    from connectors.calendar import CalendarConnector
    HAS_GOOGLE_CALENDAR = True
except ImportError:
    HAS_GOOGLE_CALENDAR = False
    GoogleAuth = None
    CalendarConnector = None

# Initialize
app = FastAPI(title="Telic", description="AI Operating System")

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

# Initialize the REAL Telic engine (all 8 primitives)
_telic_engine: Optional[TelicEngine] = None
_google_calendar: Optional['CalendarConnector'] = None

# Cache approved plans so /execute runs the SAME plan the user saw (no re-planning)
_pending_plans: Dict[str, Any] = {}  # message -> plan steps

# Conversation history for context (simple in-memory, last N messages)
_conversation_history: list = []  # [{role: "user"/"assistant", content: "..."}]
MAX_HISTORY = 10  # Keep last 10 messages for context

def get_telic_engine(force_rebuild: bool = False) -> Optional[TelicEngine]:
    """Get or create the Telic engine singleton."""
    global _telic_engine, _google_calendar
    
    if _telic_engine is not None and not force_rebuild:
        return _telic_engine
    
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
        
    model = "anthropic/claude-sonnet-4-20250514" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"
    
    # Wire up available connectors
    connectors = {}
    
    # Check for Google Calendar connection
    if HAS_GOOGLE_CALENDAR and _google_calendar and _google_calendar.connected:
        connectors["calendar"] = _google_calendar
        print("[ENGINE] Google Calendar connected - using real API")
    else:
        print("[ENGINE] Google Calendar not connected - using local storage")
    
    _telic_engine = TelicEngine(api_key=api_key, model=model, connectors=connectors)
    print(f"[ENGINE] Initialized with {len(connectors)} connectors")
    return _telic_engine

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


@app.on_event("startup")
async def startup_event():
    """Try to reconnect Google Calendar if tokens exist from previous session."""
    global _google_calendar
    
    if not HAS_GOOGLE_CALENDAR:
        print("[STARTUP] Google Calendar libraries not available")
        return
    
    try:
        auth = get_google_auth()
        
        # Check if we have existing tokens (no OAuth prompt)
        if auth._token_file.exists():
            print("[STARTUP] Found existing Google tokens, attempting reconnect...")
            
            # Load existing credentials without triggering OAuth flow
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            
            scopes = auth._resolve_scopes(['calendar'])
            creds = Credentials.from_authorized_user_file(str(auth._token_file), scopes)
            
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                auth._creds = creds
                auth._save_token()
            
            if creds and creds.valid:
                auth._creds = creds
                _google_calendar = CalendarConnector(auth)
                await _google_calendar.connect()
                print(f"[STARTUP] Google Calendar reconnected!")
                
                # Rebuild engine with the connector
                get_telic_engine(force_rebuild=True)
            else:
                print("[STARTUP] Google tokens expired or invalid")
        else:
            print("[STARTUP] No Google tokens found - user needs to connect")
            
    except Exception as e:
        print(f"[STARTUP] Google reconnect failed: {e}")


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
def get_chat_system_prompt():
    from datetime import datetime
    today = datetime.now().strftime("%A, %B %d, %Y")
    return f"""You are Telic, a privacy-first AI operating system that lives on the user's PC.
Today's date is {today}.

Your capabilities (powered by universal primitives):
1. **FILE** - Search, read, write, list, get info on any file on the PC
2. **DOCUMENT** - Parse PDFs/DOCX, extract data, create documents
3. **COMPUTE** - Financial calculations (amortization, compound interest, etc.)
4. **EMAIL** - Send, search, draft, list emails (Gmail/Outlook)
5. **CALENDAR** - List, create, update, delete events, find free time
6. **CONTACTS** - Search, find, list, create contacts
7. **DRIVE** - Cloud storage (Google Drive/OneDrive) list, search, upload, download
8. **KNOWLEDGE** - Persistent memory (remember, recall, forget)

You can chain these into multi-step workflows. For example:
- "Find the loan doc, create amortization, email to Rob" → FILE.search → DOCUMENT.parse → COMPUTE.amortization → EMAIL.send
- "Prepare for my meeting with John" → CALENDAR.search → EMAIL.search → CONTACTS.find → summarize

CRITICAL - When to take ACTION:
- ANY request to create, add, schedule, or put something on calendar -> action: true
- ANY request to send, draft, or write an email -> action: true
- ANY request to find, search, or organize files -> action: true
- When user provides details for an action (like "tonight at 8pm") -> action: true, proceed with the action
- Be BIASED TOWARD ACTION. If it sounds like the user wants something done, DO IT.
- Only set action: false for pure conversation (greetings, questions about capabilities, thanks)

For calendar events, if the user says "tonight" or "today", use {today} as the date.
Fill in reasonable defaults: if no time specified, use the typical time for that event type.
For sports games, evening events default to 7-10pm.

IMPORTANT: Respond with valid JSON:
{{
    "response": "Your conversational message explaining what you'll do",
    "action": true | false
}}

Examples:
- "Add NCAA game to my calendar" -> action: true, response: "I'll add the NCAA game to your calendar"
- "the championship game tonight" -> action: true (this IS the event details)
- "Find my loan document and create an amortization schedule" -> action: true
- "What can you do?" -> action: false
- "Thanks!" -> action: false
"""


# Routes
@app.get("/")
async def root():
    """Serve the UI with no-cache headers so updates are always picked up."""
    return FileResponse(
        Path(__file__).parent / "ui" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def has_side_effect(step):
    """Check if step has side effects (needs approval). AI decides via side_effect field."""
    return getattr(step, 'side_effect', True)  # Default to true (safer)


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Main chat endpoint with conversation memory.
    
    Flow:
    1. Add message to conversation history
    2. Plan with full context (understands follow-up responses)
    3. Auto-run read-only steps
    4. Show write steps for approval
    5. User approves → execute
    """
    global _conversation_history
    
    llm = create_secure_client_from_env()
    
    if not llm:
        return JSONResponse({
            "error": "No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
            "response": None,
            "plan": None,
            "task_id": None
        })
    
    try:
        import json
        import re
        
        # Add user message to history
        _conversation_history.append({"role": "user", "content": req.message})
        if len(_conversation_history) > MAX_HISTORY:
            _conversation_history = _conversation_history[-MAX_HISTORY:]
        
        # Build context string from recent conversation
        context_str = ""
        if len(_conversation_history) > 1:
            context_str = "Recent conversation:\n"
            for msg in _conversation_history[:-1]:  # Exclude current message
                role = "User" if msg["role"] == "user" else "Assistant"
                context_str += f"{role}: {msg['content']}\n"
            context_str += "\nCurrent request:\n"
        
        # Step 1: Ask LLM to understand intent
        result = await llm.complete_json(
            system=get_chat_system_prompt(),
            user=context_str + req.message,
            triggering_request=f"User chat: {req.message[:100]}"
        )
        
        response_text = result.get("response", "I'm not sure how to help with that.")
        needs_action = result.get("action", False)
        
        if needs_action:
            engine = get_telic_engine()
            if engine:
                # Generate plan WITH conversation context
                print(f"[CHAT] Generating plan for: {req.message[:80]}")
                
                # Pass conversation history as context
                plan_context = {"conversation": _conversation_history} if len(_conversation_history) > 1 else None
                
                exec_result = await engine.do(
                    req.message,
                    context=plan_context,
                    require_approval=True,
                )
                
                if not exec_result.plan:
                    _conversation_history.append({"role": "assistant", "content": response_text})
                    return JSONResponse({
                        "error": None,
                        "response": response_text,
                        "plan": None,
                        "task_id": None,
                    })
                
                # Check if AI needs clarification
                if exec_result.plan and exec_result.plan[0].primitive == "CLARIFY":
                    question = exec_result.plan[0].params.get("question", exec_result.plan[0].description)
                    _conversation_history.append({"role": "assistant", "content": question})
                    return JSONResponse({
                        "error": None,
                        "response": question,
                        "plan": None,
                        "task_id": None,
                    })
                
                # Step 2: Auto-run read-only steps to get actual data
                read_results = {}  # step_id -> result
                completed_steps = []
                
                for step in exec_result.plan:
                    if not has_side_effect(step):  # AI says no side effects = safe to auto-run
                        print(f"[CHAT] Auto-running read-only: {step.primitive}.{step.operation}")
                        try:
                            # Resolve any wire references from previous steps
                            resolved_params = dict(step.params)
                            for key, val in step.params.items():
                                if isinstance(val, str) and "step_" in val:
                                    m = re.match(r'step_(\d+)\.(.+)', val)
                                    if m:
                                        ref_id = int(m.group(1))
                                        path = m.group(2)
                                        if ref_id in read_results:
                                            resolved = read_results[ref_id]
                                            for part in path.split('.'):
                                                if isinstance(resolved, dict):
                                                    resolved = resolved.get(part, val)
                                            resolved_params[key] = resolved
                            
                            # Execute
                            primitive = engine._primitives.get(step.primitive.upper())
                            if primitive:
                                step_result = await primitive.execute(step.operation, resolved_params)
                                read_results[step.id] = step_result
                                completed_steps.append({
                                    "id": step.id,
                                    "description": step.description,
                                    "primitive": step.primitive,
                                    "operation": step.operation,
                                    "status": "completed",
                                    "result_summary": str(step_result)[:300] if step_result else None
                                })
                                print(f"[CHAT]   Got: {str(step_result)[:200]}")
                        except Exception as e:
                            print(f"[CHAT]   Failed: {e}")
                            completed_steps.append({
                                "id": step.id,
                                "description": step.description,
                                "primitive": step.primitive,
                                "operation": step.operation,
                                "status": "failed",
                                "error": str(e)
                            })
                
                # Step 3: Resolve wires in write steps with actual data
                write_steps = []
                for step in exec_result.plan:
                    if has_side_effect(step):  # AI says has side effects = needs approval
                        resolved_params = dict(step.params)
                        for key, val in step.params.items():
                            if isinstance(val, str) and "step_" in val:
                                m = re.match(r'step_(\d+)\.(.+)', val)
                                if m:
                                    ref_id = int(m.group(1))
                                    path = m.group(2)
                                    if ref_id in read_results:
                                        resolved = read_results[ref_id]
                                        for part in path.split('.'):
                                            if isinstance(resolved, dict):
                                                resolved = resolved.get(part, val)
                                        resolved_params[key] = resolved
                        
                        write_steps.append({
                            "id": step.id,
                            "description": step.description,
                            "primitive": step.primitive,
                            "operation": step.operation,
                            "params": resolved_params,  # Now contains ACTUAL data, not wire refs
                            "status": "pending",
                        })
                        print(f"[CHAT]   Resolved write step: {step.primitive}.{step.operation}")
                        print(f"[CHAT]     Params: {resolved_params}")
                
                # Cache for /execute - store the resolved params
                _pending_plans[req.message] = {
                    "original_plan": exec_result.plan,
                    "read_results": read_results,
                    "write_steps": write_steps,
                }
                
                # Build response
                response_parts = []
                if completed_steps:
                    response_parts.append(f"Gathered info ({len(completed_steps)} step(s))")
                if write_steps:
                    response_parts.append(f"Ready to execute ({len(write_steps)} action(s))")
                
                assistant_response = " — ".join(response_parts) if response_parts else "Here's the plan:"
                _conversation_history.append({"role": "assistant", "content": assistant_response})
                
                return JSONResponse({
                    "error": None,
                    "response": assistant_response,
                    "completed_steps": completed_steps,
                    "plan": write_steps if write_steps else None,
                    "task_id": None,
                    "needs_execution": bool(write_steps),
                })
            else:
                _conversation_history.append({"role": "assistant", "content": response_text})
                return JSONResponse({
                    "error": None,
                    "response": response_text + "\n\n(Engine not initialized - check API key)",
                    "plan": None,
                    "task_id": None,
                })
        
        # No action needed, just conversation
        _conversation_history.append({"role": "assistant", "content": response_text})
        return JSONResponse({
            "error": None,
            "response": response_text,
            "plan": None,
            "task_id": None
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "response": "Sorry, I encountered an error. Please try again.",
            "plan": None,
            "task_id": None
        })


@app.post("/clear")
async def clear_conversation():
    """Clear conversation history to start fresh."""
    global _conversation_history
    _conversation_history = []
    return JSONResponse({"status": "ok", "message": "Conversation cleared"})


class ExecuteRequest(BaseModel):
    message: str  # Original request to execute


@app.post("/execute")
async def execute_plan(req: ExecuteRequest):
    """
    Execute write steps after user approval.
    
    Read-only steps were already executed during /chat.
    This runs ONLY the write steps with resolved parameters.
    """
    print(f"[EXECUTE] Received request: {req.message[:100]}")
    
    engine = get_telic_engine()
    if not engine:
        print("[EXECUTE] ERROR: Engine not initialized")
        return JSONResponse({
            "error": "Engine not initialized - check API key",
            "success": False,
            "results": None,
        })
    
    try:
        # Use cached data from /chat
        cached = _pending_plans.pop(req.message, None)
        
        step_results = []
        
        if cached and isinstance(cached, dict) and "write_steps" in cached:
            # New format: execute only the write steps with resolved params
            write_steps = cached["write_steps"]
            print(f"[EXECUTE] Executing {len(write_steps)} write step(s)")
            
            for ws in write_steps:
                prim_name = ws["primitive"].upper()
                op = ws["operation"]
                params = ws["params"]  # Already resolved with actual data
                
                print(f"[EXECUTE]   Running {prim_name}.{op} with params: {params}")
                
                primitive = engine._primitives.get(prim_name)
                if primitive:
                    try:
                        result = await primitive.execute(op, params)
                        step_results.append({
                            "id": ws["id"],
                            "description": ws["description"],
                            "primitive": prim_name,
                            "operation": op,
                            "success": True,
                            "data": result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result),
                            "error": None,
                        })
                        print(f"[EXECUTE]   Success: {str(result)[:200]}")
                    except Exception as e:
                        step_results.append({
                            "id": ws["id"],
                            "description": ws["description"],
                            "primitive": prim_name,
                            "operation": op,
                            "success": False,
                            "data": None,
                            "error": str(e),
                        })
                        print(f"[EXECUTE]   Failed: {e}")
                else:
                    step_results.append({
                        "id": ws["id"],
                        "description": ws["description"],
                        "primitive": prim_name,
                        "operation": op,
                        "success": False,
                        "data": None,
                        "error": f"Unknown primitive: {prim_name}",
                    })
            
            all_success = all(r["success"] for r in step_results)
            return JSONResponse({
                "error": None,
                "success": all_success,
                "results": step_results,
                "final_result": step_results[-1]["data"] if step_results and step_results[-1]["success"] else None,
                "summary": "All steps completed successfully" if all_success else "Some steps failed",
            })
        
        elif cached and "original_plan" in cached:
            # Old format: use original_plan from cache
            print(f"[EXECUTE] Using cached original plan")
            exec_result = await engine.execute_plan(cached["original_plan"], request=req.message)
        else:
            print(f"[EXECUTE] No cached plan, re-planning...")
            exec_result = await engine.do(req.message, require_approval=False)
        
        print(f"[EXECUTE] Engine completed. Success: {exec_result.success}")
        
        # Format results from engine execution
        if exec_result.plan:
            for step in exec_result.plan:
                step_data = None
                if step.result and step.result.success and step.result.data is not None:
                    try:
                        import json as json_mod
                        json_mod.dumps(step.result.data)
                        step_data = step.result.data
                    except (TypeError, ValueError):
                        step_data = str(step.result.data)
                
                step_results.append({
                    "id": step.id,
                    "description": step.description,
                    "primitive": step.primitive,
                    "operation": step.operation,
                    "success": step.result.success if step.result else False,
                    "data": step_data,
                    "error": step.result.error if step.result and not step.result.success else None,
                })
        
        final = None
        if hasattr(exec_result, 'final_result') and exec_result.final_result is not None:
            try:
                import json as json_mod
                json_mod.dumps(exec_result.final_result)
                final = exec_result.final_result
            except (TypeError, ValueError):
                final = str(exec_result.final_result)
        
        return JSONResponse({
            "error": None,
            "success": exec_result.success,
            "results": step_results,
            "final_result": final,
            "summary": exec_result.error if not exec_result.success else "All steps completed successfully",
        })
    except Exception as e:
        import traceback
        print(f"[EXECUTE] EXCEPTION: {e}")
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "success": False,
            "results": None,
        })


@app.post("/execute_stream")
async def execute_plan_stream(req: ExecuteRequest):
    """
    Execute a plan with real-time step-by-step streaming via SSE.
    
    Each step sends an event as it starts and completes, so the UI
    can show sequential progress instead of "all running at once".
    """
    import json as json_mod
    
    engine = get_telic_engine()
    if not engine:
        async def error_stream():
            yield f"data: {json_mod.dumps({'type': 'error', 'error': 'Engine not initialized'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    
    queue = asyncio.Queue()
    
    async def step_callback(step_id, description, primitive, operation, success, data, error):
        """Called by the engine after each step starts/completes."""
        step_data = None
        if data is not None:
            try:
                json_mod.dumps(data)
                step_data = data
            except (TypeError, ValueError):
                step_data = str(data)
        
        event = {
            "type": "step_update",
            "step_id": step_id,
            "description": description,
            "primitive": primitive,
            "operation": operation,
            "success": success,  # None = running, True = done, False = failed
            "data": step_data,
            "error": error,
        }
        await queue.put(event)
    
    async def run_engine():
        """Run the engine in background and signal completion."""
        try:
            # Use cached write_steps from /chat - these have resolved params
            cached = _pending_plans.pop(req.message, None)
            
            if cached and isinstance(cached, dict) and "write_steps" in cached:
                # Execute only the pre-resolved write steps (read steps already ran in /chat)
                write_steps = cached["write_steps"]
                step_results = []
                
                for ws in write_steps:
                    prim_name = ws["primitive"].upper()
                    op = ws["operation"]
                    params = ws["params"]  # Already has resolved data
                    
                    # Signal start
                    await step_callback(ws["id"], ws["description"], prim_name, op, None, None, None)
                    
                    primitive = engine._primitives.get(prim_name)
                    if primitive:
                        try:
                            result = await primitive.execute(op, params)
                            await step_callback(ws["id"], ws["description"], prim_name, op, True, result, None)
                            step_results.append({"success": True, "data": result})
                        except Exception as e:
                            await step_callback(ws["id"], ws["description"], prim_name, op, False, None, str(e))
                            step_results.append({"success": False, "error": str(e)})
                    else:
                        await step_callback(ws["id"], ws["description"], prim_name, op, False, None, f"Unknown primitive: {prim_name}")
                        step_results.append({"success": False, "error": f"Unknown primitive: {prim_name}"})
                
                all_success = all(r["success"] for r in step_results)
                await queue.put({
                    "type": "complete",
                    "success": all_success,
                    "final_result": step_results[-1].get("data") if step_results and step_results[-1]["success"] else None,
                    "summary": "All steps completed successfully" if all_success else "Some steps failed",
                })
            else:
                # No cached data, run full plan
                exec_result = await engine.do(
                    req.message, 
                    require_approval=False,
                    on_step_complete=step_callback,
                )
                
                # Send final summary
                final = None
                if hasattr(exec_result, 'final_result') and exec_result.final_result is not None:
                    try:
                        json_mod.dumps(exec_result.final_result)
                        final = exec_result.final_result
                    except (TypeError, ValueError):
                        final = str(exec_result.final_result)
                
                await queue.put({
                    "type": "complete",
                    "success": exec_result.success,
                    "final_result": final,
                    "summary": exec_result.error if not exec_result.success else "All steps completed successfully",
                })
        except Exception as e:
            await queue.put({"type": "error", "error": str(e)})
        finally:
            await queue.put(None)  # Sentinel to end stream
    
    async def event_stream():
        """SSE generator that yields events as they arrive."""
        task = asyncio.create_task(run_engine())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json_mod.dumps(event)}\n\n"
        finally:
            if not task.done():
                task.cancel()
    
    return StreamingResponse(
        event_stream(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        },
    )


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


# =============================================================================
# GOOGLE CALENDAR - SIMPLE OAUTH FLOW
# =============================================================================

@app.get("/google/status")
async def google_status():
    """Check Google Calendar connection status."""
    global _google_calendar
    
    if not HAS_GOOGLE_CALENDAR:
        return JSONResponse({
            "connected": False,
            "error": "Google API libraries not installed. Run: pip install google-api-python-client google-auth-oauthlib",
            "has_credentials_file": False,
        })
    
    auth = get_google_auth()
    has_creds = auth.has_credentials_file()
    connected = _google_calendar is not None and _google_calendar.connected
    
    calendars = []
    if connected:
        try:
            calendars = await _google_calendar.list_calendars()
        except Exception as e:
            print(f"[GOOGLE] Error listing calendars: {e}")
    
    return JSONResponse({
        "connected": connected,
        "has_credentials_file": has_creds,
        "calendars": calendars,
        "setup_instructions": auth.get_setup_instructions() if not has_creds else None,
    })


@app.post("/google/connect")
async def google_connect():
    """Connect to Google Calendar via OAuth."""
    global _google_calendar, _telic_engine
    
    if not HAS_GOOGLE_CALENDAR:
        return JSONResponse({
            "success": False,
            "error": "Google API libraries not installed. Run: pip install google-api-python-client google-auth-oauthlib",
        })
    
    auth = get_google_auth()
    
    if not auth.has_credentials_file():
        return JSONResponse({
            "success": False,
            "error": "OAuth credentials file not found",
            "setup_instructions": auth.get_setup_instructions(),
        })
    
    try:
        # This opens a browser for OAuth
        print("[GOOGLE] Starting OAuth flow...")
        creds = await auth.get_credentials(['calendar'])
        
        if not creds:
            return JSONResponse({
                "success": False,
                "error": "OAuth flow failed or was cancelled",
            })
        
        # Create and connect the calendar connector
        _google_calendar = CalendarConnector(auth)
        await _google_calendar.connect()
        
        # Rebuild the engine with the new connector
        _telic_engine = None
        get_telic_engine(force_rebuild=True)
        
        # List calendars to confirm connection
        calendars = await _google_calendar.list_calendars()
        
        print(f"[GOOGLE] Connected! Found {len(calendars)} calendars")
        
        return JSONResponse({
            "success": True,
            "calendars": calendars,
            "message": f"Connected to Google Calendar. Found {len(calendars)} calendars.",
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e),
        })


@app.get("/google/calendars")
async def list_google_calendars():
    """List all Google Calendars."""
    global _google_calendar
    
    if not _google_calendar or not _google_calendar.connected:
        return JSONResponse({
            "error": "Not connected to Google Calendar",
            "calendars": [],
        })
    
    try:
        calendars = await _google_calendar.list_calendars()
        return JSONResponse({"calendars": calendars})
    except Exception as e:
        return JSONResponse({"error": str(e), "calendars": []})


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
            storage_path=str(Path.home() / ".telic"),
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


# =============================================================================
# PHASE 7: PRIVACY & AUDIT ENDPOINTS
# =============================================================================

@app.get("/privacy/audit")
async def get_audit_log(limit: int = 50):
    """
    Get recent external data transmissions.
    
    Every time data is sent to an LLM, it's logged here.
    Users can review exactly what was sent externally.
    """
    records = audit_logger.get_transmissions(limit=limit)
    return JSONResponse({
        "transmissions": [r.to_dict() for r in records],
        "count": len(records),
    })


@app.get("/privacy/audit/stats")
async def get_audit_stats():
    """
    Get transmission statistics for the last 24 hours.
    
    Shows: total calls, bytes sent, PII detected, destinations used.
    """
    stats = audit_logger.get_stats()
    return JSONResponse(stats)


@app.get("/privacy/audit/today")
async def get_audit_today():
    """
    Get human-readable summary of today's transmissions.
    """
    summary = audit_logger.get_today_summary()
    return JSONResponse({
        "summary": summary,
    })


@app.post("/privacy/redact")
async def test_redaction(text: str):
    """
    Test PII redaction on a piece of text.
    
    Use this to see what would be redacted before sending to LLM.
    """
    result = redaction_engine.redact(text)
    return JSONResponse({
        "original_length": len(text),
        "redacted_text": result.redacted_text,
        "redaction_count": result.redaction_count,
        "had_pii": result.had_pii,
        "redactions": result.redactions,
    })


@app.get("/privacy/trust")
async def get_trust_levels():
    """
    Get all trust level settings.
    
    Shows which actions require approval vs auto-approve.
    """
    levels = trust_manager.get_all_levels()
    return JSONResponse({
        "trust_levels": levels,
        "legend": {
            "always_ask": "🔴 Always require explicit approval",
            "ask_once": "🟡 Ask once, offer to remember pattern",
            "auto_approve": "🟢 Execute without asking",
        }
    })


@app.post("/privacy/trust/{action_type}")
async def set_trust_level(action_type: str, level: str):
    """
    Set trust level for an action type.
    
    Levels: always_ask, ask_once, auto_approve
    """
    try:
        trust_level = TrustLevel(level)
        trust_manager.set_trust_level(action_type, trust_level)
        return JSONResponse({
            "success": True,
            "action_type": action_type,
            "level": level,
        })
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/privacy/pending")
async def get_pending_actions():
    """
    Get all actions awaiting approval.
    
    These are actions that need user confirmation before executing.
    """
    pending = approval_gateway.get_pending()
    return JSONResponse({
        "pending": [a.to_dict() for a in pending],
        "count": len(pending),
    })


@app.post("/privacy/approve/{action_id}")
async def approve_action(action_id: str):
    """
    Approve a pending action.
    
    The action will be executed immediately.
    """
    try:
        result = await approval_gateway.approve(action_id)
        return JSONResponse({
            "success": True,
            "action_id": action_id,
            "status": result.status.value,
            "result": result.result,
        })
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/privacy/reject/{action_id}")
async def reject_action(action_id: str, reason: str = None):
    """
    Reject a pending action.
    
    The action will not be executed.
    """
    try:
        result = await approval_gateway.reject(action_id, reason=reason)
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


@app.get("/control/history")
async def get_action_history(limit: int = 50, category: str = None, status: str = None):
    """
    Get action history with optional filtering.
    
    Shows all actions that have been recorded, including their status.
    """
    actions = action_history.get_recent(limit=limit)
    
    # Optional filtering
    if category:
        actions = [a for a in actions if a.category.value == category]
    if status:
        actions = [a for a in actions if a.status.value == status]
    
    return JSONResponse({
        "actions": [a.to_dict() for a in actions],
        "count": len(actions),
    })


@app.get("/control/history/{action_id}")
async def get_action_detail(action_id: str):
    """
    Get details of a specific action.
    """
    record = action_history.get_by_id(action_id)
    if not record:
        raise HTTPException(status_code=404, detail="Action not found")
    
    return JSONResponse(record.to_dict())


@app.post("/control/approve")
async def approve_control_action(request: ApproveActionRequest):
    """
    Approve an action via the control layer.
    
    This creates a checkpoint for undo, executes the action, and logs it.
    Supports trust level learning via remember_pattern flag.
    """
    action_id = request.action_id
    
    try:
        # Get the action from approval gateway
        result = await approval_gateway.approve(
            action_id,
            modifications=request.modifications,
            remember_pattern=request.remember_pattern,
            pattern_context=request.pattern_context,
        )
        
        # Mark completed in action history
        action_history.mark_completed(action_id, result=result.result)
        
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


@app.post("/control/reject")
async def reject_control_action(request: ApproveActionRequest):
    """
    Reject an action via the control layer.
    """
    action_id = request.action_id
    
    try:
        result = await approval_gateway.reject(action_id)
        return JSONResponse({
            "success": True,
            "action_id": action_id,
        })
    except ValueError as e:
        return JSONResponse({
            "success": False,
            "error": str(e),
        }, status_code=400)


@app.post("/control/undo")
async def undo_action(request: UndoActionRequest):
    """
    Undo a completed action.
    
    Only works for actions that have checkpoints and are within the undo window.
    """
    action_id = request.action_id
    
    try:
        # Get action record
        record = action_history.get_by_id(action_id)
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
            result = await undo_manager.undo(checkpoint_id)
            if result.status.value == "completed":
                action_history.mark_undone(action_id)
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
            action_history.mark_undone(action_id)
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


@app.get("/control/checkpoints")
async def get_checkpoints(limit: int = 20):
    """
    Get recent undo checkpoints.
    """
    checkpoints = undo_manager.get_checkpoints(limit=limit)
    return JSONResponse({
        "checkpoints": [c.to_dict() for c in checkpoints],
        "count": len(checkpoints),
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
    
    # Load .env file (API keys, config) — checks both apex/ and repo root
    try:
        from dotenv import load_dotenv
        load_dotenv()  # apex/.env
        load_dotenv(Path(__file__).parent.parent / ".env")  # repo root .env
    except ImportError:
        pass
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                       TELIC AI OS                             ║
║            The AI Operating System with Purpose               ║
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
