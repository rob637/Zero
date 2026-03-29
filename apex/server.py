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

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.core import Orchestrator
from src.core.llm import create_client_from_env
from src.skills import FileOrganizerSkill, DuplicateFinderSkill, TempCleanerSkill

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

When the user asks for help with something you can do:
1. Acknowledge their request conversationally
2. Tell them you'll analyze the situation
3. Set "action" to the appropriate skill name

When the user asks what you can do, explain your capabilities warmly.

When the user asks something you can't help with, be honest and suggest what you CAN help with.

IMPORTANT: You must respond with valid JSON in this exact format:
{
    "response": "Your conversational message to the user",
    "action": "file_organizer" | "duplicate_finder" | "temp_cleaner" | null,
    "target": "path or folder name if mentioned, or null"
}

Examples:
- "organize my downloads" -> action: "file_organizer", target: "Downloads"
- "find duplicates in D:\\Photos" -> action: "duplicate_finder", target: "D:\\Photos"
- "my pc is slow" -> action: "temp_cleaner", target: null
- "clean up my computer" -> action: null (ask what specifically they want)
- "what can you do?" -> action: null (just explain)
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
        target = result.get("target")
        
        # If there's an action, route to skill
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


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok", "llm_configured": create_client_from_env() is not None}


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
