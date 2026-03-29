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
from src.skills import FileOrganizerSkill

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


class ApproveRequest(BaseModel):
    task_id: str
    approved_indices: list[int]


class RejectRequest(BaseModel):
    task_id: str


# Routes
@app.get("/")
async def root():
    """Serve the UI."""
    return FileResponse(Path(__file__).parent / "ui" / "index.html")


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
