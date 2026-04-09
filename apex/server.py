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

# Load .env FIRST before any other imports that might use env vars
try:
    from dotenv import load_dotenv
    load_dotenv()  # apex/.env
    load_dotenv(Path(__file__).parent.parent / ".env")  # repo root .env
except ImportError:
    pass

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.core import Orchestrator, workflow_engine, proactive_scanner
from src.core.llm import create_client_from_env

# Telic Engine - the REAL engine with all primitives
from apex_engine import Apex as TelicEngine

# ReAct Agent - native function calling
from react_agent import ReActAgent, Tool, primitives_to_tools, Step, StepStatus, AgentState

# Session persistence
import sessions as session_store

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

# Connector Registry Infrastructure
from connectors.registry import (
    ConnectorRegistry, 
    get_registry, 
    ConnectionStatus,
    ConnectorMetadata,
)
from connectors.credentials import (
    CredentialStore,
    get_credential_store,
)
from connectors.oauth_flow import (
    OAuthFlow,
    get_oauth_flow,
    OAUTH_PROVIDERS,
)
from connectors.resolver import (
    PrimitiveResolver,
    ExecutionMode,
    AggregationStrategy,
    get_resolver,
)

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
_gmail_connector: Optional['GmailConnector'] = None

# Track which Google services have authorized scopes (populated during OAuth callback)
_google_connected_services: set = set()  # e.g. {"gmail", "calendar", "drive", "contacts", "photos"}

# Cache approved plans so /execute runs the SAME plan the user saw (no re-planning)
_pending_plans: Dict[str, Any] = {}  # message -> plan steps

# Conversation history for context (simple in-memory, last N messages)
_conversation_history: list = []  # [{role: "user"/"assistant", content: "..."}]
MAX_HISTORY = 10  # Keep last 10 messages for context

# ReAct Agent state (per-session, stored by session_id in production)
_react_agent: Optional[ReActAgent] = None
_react_state: Optional[AgentState] = None

# Session-based conversation (like ChatGPT/Gemini)
_session_messages: list = []  # Full conversation history for session
_session_agent: Optional[ReActAgent] = None   # Persistent agent for session
_session_id: Optional[str] = None  # Current session ID for persistence

def get_telic_engine(force_rebuild: bool = False) -> Optional[TelicEngine]:
    """Get or create the Telic engine singleton.
    
    Auto-discovers all connected connectors from the registry
    and credential store instead of hardcoding individual services.
    """
    global _telic_engine, _google_calendar, _react_agent
    
    if _telic_engine is not None and not force_rebuild:
        return _telic_engine
    
    # When rebuilding engine, also reset the react agent so it picks up new tools
    if force_rebuild:
        _react_agent = None
    
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
        
    model = "anthropic/claude-sonnet-4-20250514" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"
    
    # Auto-discover connectors from registry + credentials
    connectors = _build_connectors_from_registry()
    
    _telic_engine = TelicEngine(api_key=api_key, model=model, connectors=connectors)
    print(f"[ENGINE] Initialized with {len(connectors)} connectors: {list(connectors.keys())}")
    return _telic_engine


def _build_connectors_from_registry() -> Dict[str, Any]:
    """
    Scan the registry and credential store to auto-discover all
    connected services and build the connectors dict for the engine.
    
    This replaces manual hardcoding of individual connectors.
    """
    from connectors.registry import ConnectorRegistry
    
    connectors: Dict[str, Any] = {}
    
    # 1. Wire up already-initialized connectors (Google services from OAuth flow)
    if HAS_GOOGLE_CALENDAR and _google_calendar and _google_calendar.connected:
        connectors["calendar"] = _google_calendar
    if _gmail_connector:
        connectors["gmail"] = _gmail_connector
    
    # 2. Scan registry for all registered connectors and try to instantiate
    #    those that have valid credentials
    registry = ConnectorRegistry()
    store = get_cred_store()
    
    # Map from registry connector names to engine connector keys
    # (engine uses short keys, registry uses full names)
    registry_to_engine = {
        "gmail": "gmail",
        "google_calendar": "calendar",
        "google_drive": "drive",
        "google_contacts": "contacts",
        "google_sheets": "google_sheets",
        "google_slides": "google_slides",
        "google_photos": "google_photos",
        "outlook": "outlook",
        "outlook_calendar": "outlook_calendar",
        "onedrive": "onedrive",
        "microsoft_todo": "microsoft_todo",
        "microsoft_excel": "excel",
        "microsoft_powerpoint": "powerpoint",
        "microsoft_contacts": "contacts_microsoft",
        "onenote": "onenote",
        "teams": "teams",
        "slack": "slack",
        "discord": "discord",
        "github": "github",
        "jira": "jira",
        "todoist": "todoist",
        "spotify": "spotify",
        "dropbox": "dropbox",
        "twilio": "twilio",
        "twitter": "twitter",
        "smartthings": "smartthings",
        "youtube": "youtube",
        "web_search": "web_search",
        "weather": "weather",
        "news": "news",
        "notion": "notion",
        "linear": "linear",
        "trello": "trello",
        "airtable": "airtable",
        "zoom": "zoom",
        "linkedin": "linkedin",
        "reddit": "reddit",
    }
    
    # Check which providers have valid credentials
    connected_providers = set()
    try:
        for provider in store.list_providers():
            if store.has_valid(provider):
                connected_providers.add(provider)
    except Exception:
        pass
    
    # Also check env vars for token-based services
    env_tokens = {
        "github": "GITHUB_TOKEN",
        "slack": "SLACK_BOT_TOKEN",
        "discord": "DISCORD_BOT_TOKEN",
        "todoist": "TODOIST_API_TOKEN",
        "spotify": "SPOTIFY_CLIENT_ID",
        "smartthings": "SMARTTHINGS_TOKEN",
        "twilio": "TWILIO_ACCOUNT_SID",
        "weather": "OPENWEATHERMAP_API_KEY",
        "news": "NEWSAPI_KEY",
        "notion": "NOTION_API_KEY",
        "linear": "LINEAR_API_KEY",
        "trello": "TRELLO_API_KEY",
        "airtable": "AIRTABLE_API_KEY",
        "zoom": "ZOOM_API_KEY",
        "linkedin": "LINKEDIN_ACCESS_TOKEN",
        "reddit": "REDDIT_CLIENT_ID",
    }
    for provider, env_var in env_tokens.items():
        if os.environ.get(env_var):
            connected_providers.add(provider)
    
    # Also add Google services that were connected via OAuth
    if _google_connected_services:
        connected_providers.add("google")
    
    # Check Microsoft auth
    if "microsoft" in connected_providers or os.environ.get("AZURE_CLIENT_ID"):
        connected_providers.add("microsoft")
    
    # Instantiate connectors for connected providers
    for metadata in registry.list_connectors():
        engine_key = registry_to_engine.get(metadata.name)
        if not engine_key:
            continue
        
        # Skip if already wired (e.g., Gmail/Calendar from OAuth)
        if engine_key in connectors:
            continue
        
        # Check if this provider has credentials
        if metadata.provider not in connected_providers:
            continue
        
        try:
            instance = metadata.connector_class()
            connectors[engine_key] = instance
            print(f"[ENGINE] Auto-wired: {metadata.display_name} -> {engine_key}")
        except Exception as e:
            print(f"[ENGINE] Failed to instantiate {metadata.name}: {e}")
    
    return connectors


def get_react_agent() -> Optional[ReActAgent]:
    """Get or create the ReAct agent using Telic primitives."""
    global _react_agent
    
    if _react_agent is not None:
        return _react_agent
    
    # Need API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fall back to OpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
    
    # Get the Telic engine (has all primitives)
    engine = get_telic_engine()
    if not engine:
        return None
    
    # Convert ALL primitives to tools - selection happens per-request now
    tools = primitives_to_tools(engine._primitives)
    print(f"[REACT] Loaded {len(tools)} tools from {len(engine._primitives)} primitives")
    
    # Create LLM client
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        llm_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    else:
        import openai
        llm_client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    
    from datetime import datetime, timedelta
    now = datetime.now()
    # Build date context with upcoming days for accurate scheduling
    date_context = f"""TODAY: {now.strftime("%A, %B %d, %Y")} ({now.strftime("%Y-%m-%d")})
This week:
"""
    for i in range(7):
        d = now + timedelta(days=i)
        date_context += f"  {d.strftime('%A %b %d')}: {d.strftime('%Y-%m-%d')}\n"
    
    system_prompt = f"""You are Ziggy, an AI assistant that helps users get things done.

{date_context}

Use the available tools to accomplish what the user asks. You can call multiple tools in parallel when the calls are independent.

Be efficient — don't repeat searches with slight variations. If a search returns no results, broaden the query or try a different approach.

IMPORTANT BEHAVIORS:
- If a search returns multiple results, STOP and ask the user which one they want
- If information is unclear or missing, ASK before guessing  
- Show computed results (calculations, data) to the user and ask if they want to proceed
- Be conversational - explain what you're doing and what you found

When you have completed the task, respond with a summary of what was done."""
    
    _react_agent = ReActAgent(
        llm_client=llm_client,
        tools=tools,
        system_prompt=system_prompt,
    )
    
    return _react_agent


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
    """Try to reconnect Google services if tokens exist from previous session."""
    global _google_calendar, _gmail_connector, _google_connected_services
    
    if not HAS_GOOGLE_CALENDAR:
        print("[STARTUP] Google API libraries not available")
        return
    
    try:
        auth = get_google_auth()
        
        # Check if we have existing tokens (no OAuth prompt)
        if auth._token_file.exists():
            print("[STARTUP] Found existing Google tokens, attempting reconnect...")
            
            # Load existing credentials without triggering OAuth flow
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            
            # Load credentials with ALL possible scopes so we don't lose any
            # Google's library restricts creds to only the scopes you request,
            # so we must request everything the token might contain
            all_scopes = auth._resolve_scopes(['calendar', 'gmail', 'drive', 'contacts', 'photos', 'sheets', 'slides'])
            creds = Credentials.from_authorized_user_file(str(auth._token_file), all_scopes)
            
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                auth._creds = creds
                auth._save_token()
            
            if creds and creds.valid:
                auth._creds = creds
                
                # Check what scopes we have - populate _google_connected_services
                token_scopes = set(creds.scopes or [])
                
                # Map OAuth scopes to service names
                scope_to_service = {
                    'calendar': 'calendar',
                    'gmail': 'gmail', 
                    'mail.google': 'gmail',
                    'drive': 'drive',
                    'contacts': 'contacts',
                    'photoslibrary': 'photos',
                    'spreadsheets': 'sheets',
                    'presentations': 'slides',
                }
                
                # Populate connected services based on token scopes
                _google_connected_services.clear()
                for scope in token_scopes:
                    for key, service in scope_to_service.items():
                        if key in scope.lower():
                            _google_connected_services.add(service)
                
                has_calendar = 'calendar' in _google_connected_services
                has_gmail = 'gmail' in _google_connected_services
                
                print(f"[STARTUP] Token scopes: {_google_connected_services}")
                
                # Connect Calendar
                if has_calendar:
                    _google_calendar = CalendarConnector(auth)
                    await _google_calendar.connect()
                    print(f"[STARTUP] Google Calendar reconnected!")
                
                # Connect Gmail
                if has_gmail:
                    try:
                        from connectors.gmail import GmailConnector
                        _gmail_connector = GmailConnector(auth)
                        if await _gmail_connector.connect():
                            print("[STARTUP] Gmail reconnected!")
                        else:
                            print("[STARTUP] Gmail connection failed")
                            _gmail_connector = None
                    except Exception as gmail_err:
                        print(f"[STARTUP] Gmail reconnect failed: {gmail_err}")
                        _gmail_connector = None
                else:
                    print("[STARTUP] Gmail scopes not in token - user needs to re-authenticate with Gmail access")
            else:
                print("[STARTUP] Google tokens expired or invalid")
                
            # Rebuild engine with connectors
            get_telic_engine(force_rebuild=True)
        else:
            print("[STARTUP] No Google tokens found - user needs to connect")
            
    except Exception as e:
        print(f"[STARTUP] Google reconnect failed: {e}")

    # Start ProactiveMonitor with any connected services
    try:
        monitor = get_proactive_monitor()
        
        # Connect Google services if available
        if _google_calendar and _google_calendar.connected:
            monitor.connect_service("calendar", _google_calendar)
        if _gmail_connector:
            monitor.connect_service("email", _gmail_connector)
        
        # Connect services available via env vars
        if os.environ.get("GITHUB_TOKEN"):
            try:
                from connectors.github import GitHubConnector
                gh = GitHubConnector()
                if await gh.connect():
                    monitor.connect_service("github", gh)
            except Exception:
                pass
        
        if os.environ.get("SLACK_BOT_TOKEN"):
            try:
                from connectors.slack import SlackConnector
                sl = SlackConnector()
                if await sl.connect():
                    monitor.connect_service("slack", sl)
            except Exception:
                pass
        
        await monitor.start()
        print(f"[STARTUP] ProactiveMonitor started with services: {list(monitor._service_adapters.keys())}")
    except Exception as e:
        print(f"[STARTUP] ProactiveMonitor start failed (non-fatal): {e}")


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
    return f"""You are Ziggy, an AI assistant that connects all your services and takes action for you.
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


# =============================================================================
# SETUP & CAPABILITIES - User-friendly configuration
# =============================================================================

@app.get("/capabilities")
async def get_capabilities():
    """
    Get all capabilities and which services support them.
    
    User sees: "What do you want Telic to handle?" with service options.
    """
    registry = ConnectorRegistry()
    connectors = registry.list_connectors()
    
    # Build capability -> services mapping
    capabilities = {}
    capability_meta = {
        "EMAIL": {"icon": "📧", "name": "Email", "description": "Send, read, and search emails"},
        "CALENDAR": {"icon": "📅", "name": "Calendar", "description": "Create events, check availability, reminders"},
        "CHAT": {"icon": "💬", "name": "Chat", "description": "Send messages to Slack, Teams, Discord"},
        "CLOUD_STORAGE": {"icon": "📁", "name": "Files", "description": "Access Google Drive, OneDrive, Dropbox"},
        "TASK": {"icon": "✅", "name": "Tasks", "description": "Manage to-dos and tasks"},
        "CONTACTS": {"icon": "👥", "name": "Contacts", "description": "Find and manage contacts"},
        "DEVTOOLS": {"icon": "💻", "name": "Dev Tools", "description": "GitHub issues, Jira tickets, PRs"},
        "DOCUMENT": {"icon": "📄", "name": "Documents", "description": "Parse, summarize, create documents"},
        "SPREADSHEET": {"icon": "📊", "name": "Spreadsheets", "description": "Google Sheets, Excel"},
        "PRESENTATION": {"icon": "📽️", "name": "Presentations", "description": "Google Slides, PowerPoint"},
        "NOTES": {"icon": "📝", "name": "Notes", "description": "OneNote, Apple Notes"},
        "MEDIA": {"icon": "🎵", "name": "Media", "description": "Play music, control Spotify"},
        "MEETING": {"icon": "🎥", "name": "Meetings", "description": "Schedule Zoom, Teams, Meet calls"},
        "SMS": {"icon": "📱", "name": "SMS", "description": "Send text messages via Twilio"},
        "PHOTO": {"icon": "📷", "name": "Photos", "description": "Google Photos library"},
        "HOME_AUTOMATION": {"icon": "🏠", "name": "Smart Home", "description": "Control smart devices"},
        "SOCIAL": {"icon": "🐦", "name": "Social", "description": "Twitter/X posting"},
    }
    
    for c in connectors:
        for prim in c.primitives:
            if prim not in capabilities:
                meta = capability_meta.get(prim, {"icon": "⚡", "name": prim.title(), "description": ""})
                capabilities[prim] = {
                    "id": prim,
                    "name": meta["name"],
                    "icon": meta["icon"],
                    "description": meta["description"],
                    "services": [],
                }
            capabilities[prim]["services"].append({
                "id": c.name,
                "name": c.display_name,
                "provider": c.provider,
                "icon": c.icon or c.provider,
                "connected": False,  # Will be updated by /services endpoint
            })
    
    return JSONResponse({
        "capabilities": list(capabilities.values()),
    })


@app.get("/services")
async def get_services():
    """
    Get all available services with connection status.
    
    User sees a grid of services they can connect.
    Checks both environment variables AND stored credentials.
    """
    registry = ConnectorRegistry()
    connectors = registry.list_connectors()
    
    services = []
    
    # Check connection status for each - be accurate about what's actually connected
    global _google_calendar, _gmail_connector, _google_connected_services
    
    calendar_connected = _google_calendar is not None and _google_calendar.connected
    gmail_connected = _gmail_connector is not None
    
    # Check env vars for other services
    github_connected = bool(os.environ.get("GITHUB_TOKEN"))
    jira_connected = bool(os.environ.get("JIRA_API_TOKEN") and os.environ.get("JIRA_URL"))
    slack_connected = bool(os.environ.get("SLACK_BOT_TOKEN"))
    
    # Use _google_connected_services to track which Google services are authorized
    status_map = {
        "gmail": gmail_connected or 'gmail' in _google_connected_services,
        "google_calendar": calendar_connected or 'calendar' in _google_connected_services,
        "google_drive": 'drive' in _google_connected_services,
        "google_contacts": 'contacts' in _google_connected_services,
        "google_photos": 'photos' in _google_connected_services,
        "google_sheets": 'sheets' in _google_connected_services,
        "google_slides": 'slides' in _google_connected_services,
        "github": github_connected,
        "jira": jira_connected,
        "slack": slack_connected,
    }
    
    # Also check credential store for stored tokens
    try:
        store = get_cred_store()
        for provider in store.list_providers():
            if store.has_valid(provider):
                status_map[provider] = True
                # Map provider-level credentials to individual service connectors
                if provider == "microsoft":
                    for svc in ["outlook", "outlook_calendar", "onedrive", "microsoft_todo", "onenote", "teams", "microsoft_excel", "microsoft_powerpoint", "microsoft_contacts"]:
                        status_map[svc] = True
    except Exception:
        pass
    
    for c in connectors:
        connected = status_map.get(c.name, False)
        services.append({
            "id": c.name,
            "name": c.display_name,
            "provider": c.provider,
            "icon": c.icon or c.provider,
            "description": c.description,
            "capabilities": c.primitives,
            "connected": connected,
            "setup_type": "oauth" if c.provider in ("google", "microsoft") else "token",
        })
    
    return JSONResponse({
        "services": sorted(services, key=lambda x: (not x["connected"], x["provider"], x["name"])),
    })


@app.get("/setup")
async def setup_page():
    """Serve the setup/connections page."""
    return FileResponse(
        Path(__file__).parent / "ui" / "setup.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# =============================================================================
# CREDENTIALS API - Secure token/API key management
# =============================================================================

_credential_store = None

def get_cred_store():
    """Get singleton credential store."""
    global _credential_store
    if _credential_store is None:
        _credential_store = get_credential_store()
    return _credential_store


class SaveCredentialRequest(BaseModel):
    """Request to save a credential."""
    provider: str
    credential_type: str = "api_key"  # api_key, oauth_token, client_credentials
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


@app.get("/credentials")
async def list_credentials():
    """
    List all stored credentials (without exposing secrets).
    
    Returns provider names, types, and status - NOT the actual credentials.
    """
    store = get_cred_store()
    providers = store.list_providers()
    
    credentials = []
    for provider in providers:
        cred = store.get(provider)
        if cred:
            credentials.append({
                "provider": provider,
                "type": cred.credential_type.value,
                "created_at": cred.created_at.isoformat() if cred.created_at else None,
                "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
                "is_expired": cred.is_expired(),
                "has_refresh_token": bool(cred.data.get("refresh_token")),
                "scopes": cred.scopes,
            })
    
    return JSONResponse({"credentials": credentials})


@app.post("/credentials")
async def save_credential(req: SaveCredentialRequest):
    """
    Save a credential (API key or token).
    
    Credentials are stored encrypted on disk.
    """
    store = get_cred_store()
    
    try:
        if req.credential_type == "api_key" and req.api_key:
            success = store.save_api_key(
                provider=req.provider,
                api_key=req.api_key,
                extra_data=req.extra,
            )
        elif req.credential_type == "client_credentials" and req.client_id:
            success = store.save_client_credentials(
                provider=req.provider,
                client_id=req.client_id,
                client_secret=req.client_secret,
                extra_data=req.extra,
            )
        elif req.credential_type == "oauth_token" and req.access_token:
            success = store.save_token(
                provider=req.provider,
                access_token=req.access_token,
                refresh_token=req.refresh_token,
                extra_data=req.extra,
            )
        else:
            return JSONResponse(
                {"success": False, "error": "Invalid credential type or missing required fields"},
                status_code=400,
            )
        
        if success:
            # Also set as environment variable for current session
            env_var_map = {
                "github": "GITHUB_TOKEN",
                "slack": "SLACK_BOT_TOKEN",
                "discord": "DISCORD_BOT_TOKEN",
                "jira": "JIRA_API_TOKEN",
                "todoist": "TODOIST_API_TOKEN",
                "twilio": "TWILIO_AUTH_TOKEN",
                "spotify": "SPOTIFY_CLIENT_ID",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
            }
            if req.provider in env_var_map and req.api_key:
                os.environ[env_var_map[req.provider]] = req.api_key
            
            return JSONResponse({
                "success": True,
                "message": f"Credential saved for {req.provider}",
            })
        else:
            return JSONResponse(
                {"success": False, "error": "Failed to save credential"},
                status_code=500,
            )
    except Exception as e:
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


@app.delete("/credentials/{provider}")
async def delete_credential(provider: str):
    """Delete a stored credential."""
    store = get_cred_store()
    
    if store.delete(provider):
        return JSONResponse({"success": True, "message": f"Deleted credential for {provider}"})
    else:
        return JSONResponse(
            {"success": False, "error": f"No credential found for {provider}"},
            status_code=404,
        )


@app.get("/credentials/{provider}/status")
async def credential_status(provider: str):
    """Check credential status for a provider."""
    store = get_cred_store()
    cred = store.get(provider)
    
    if not cred:
        return JSONResponse({
            "exists": False,
            "valid": False,
            "provider": provider,
        })
    
    return JSONResponse({
        "exists": True,
        "valid": not cred.is_expired(),
        "type": cred.credential_type.value,
        "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
        "needs_refresh": store.needs_refresh(provider),
        "provider": provider,
    })


# =============================================================================
# OAUTH POPUP FLOW - Browser popup for OAuth instead of redirect
# =============================================================================

@app.get("/oauth/start/{provider}")
async def oauth_start(provider: str, scopes: Optional[str] = None):
    """
    Start OAuth flow - returns URL to open in popup.
    
    The popup will redirect to /oauth/callback which handles the token exchange
    and closes the popup with a message to the parent window.
    """
    from connectors.oauth_flow import OAUTH_PROVIDERS
    
    if provider not in OAUTH_PROVIDERS:
        return JSONResponse(
            {"error": f"Unknown OAuth provider: {provider}"},
            status_code=400,
        )
    
    try:
        # For Google, use GoogleAuth which handles credentials from file
        if provider == "google":
            auth = get_google_auth()
            if not auth.has_credentials_file():
                return JSONResponse({
                    "error": "Google OAuth credentials not configured",
                    "setup_instructions": auth.get_setup_instructions(),
                }, status_code=400)
            
            # Start with the requested scopes
            scope_names = ["calendar", "gmail"]  # Always include core services
            if scopes:
                for s in scopes.split(","):
                    if s not in scope_names:
                        scope_names.append(s)
            
            # CRITICAL: Preserve existing scopes from current token
            # Otherwise connecting a new service loses access to previously connected ones
            if auth._token_file.exists():
                try:
                    from google.oauth2.credentials import Credentials
                    existing_creds = Credentials.from_authorized_user_file(str(auth._token_file))
                    if existing_creds and existing_creds.scopes:
                        # Map existing OAuth scopes back to scope names
                        scope_url_to_name = {
                            'calendar': 'calendar',
                            'gmail': 'gmail',
                            'drive': 'drive',
                            'contacts': 'contacts',
                            'photoslibrary': 'photos',
                            'spreadsheets': 'sheets',
                            'presentations': 'slides',
                        }
                        for scope_url in existing_creds.scopes:
                            for key, name in scope_url_to_name.items():
                                if key in scope_url.lower() and name not in scope_names:
                                    scope_names.append(name)
                                    print(f"[OAUTH] Preserving existing scope: {name}")
                except Exception as e:
                    print(f"[OAUTH] Could not read existing scopes: {e}")
            
            print(f"[OAUTH] Requesting scopes: {scope_names}")
            resolved_scopes = auth._resolve_scopes(scope_names)
            
            # Generate auth URL
            from google_auth_oauthlib.flow import InstalledAppFlow
            import secrets
            
            flow = InstalledAppFlow.from_client_secrets_file(
                str(auth._credentials_file),
                scopes=resolved_scopes,
                redirect_uri="http://127.0.0.1:8000/oauth/callback",
            )
            
            state = secrets.token_urlsafe(32)
            auth_url, _ = flow.authorization_url(
                state=state,
                access_type="offline",
                prompt="consent",
            )
            
            # Store state for callback
            _oauth_pending_states[state] = {
                "provider": "google", 
                "flow": flow,
                "scopes": resolved_scopes,
            }
            
            return JSONResponse({
                "auth_url": auth_url,
                "state": state,
                "provider": provider,
            })
        
        # For Discord, check env vars first
        if provider == "discord":
            client_id = os.environ.get("DISCORD_CLIENT_ID")
            client_secret = os.environ.get("DISCORD_CLIENT_SECRET")
            
            print(f"[DISCORD] Checking env: client_id={bool(client_id)}, client_secret={bool(client_secret)}")
            
            if client_id and client_secret:
                import secrets
                state = secrets.token_urlsafe(32)
                
                # Discord OAuth scopes - user-only (no bot, no server required)
                discord_scopes = ["identify", "email", "guilds"]
                scope_str = "%20".join(discord_scopes)
                
                redirect_uri = "http://127.0.0.1:8000/oauth/callback"
                auth_url = (
                    f"https://discord.com/api/oauth2/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&response_type=code"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                _oauth_pending_states[state] = {
                    "provider": "discord",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
                
                return JSONResponse({
                    "auth_url": auth_url,
                    "state": state,
                    "provider": provider,
                })
        
        # For Microsoft, check env vars
        if provider == "microsoft":
            client_id = os.environ.get("MICROSOFT_CLIENT_ID")
            client_secret = os.environ.get("MICROSOFT_CLIENT_SECRET")
            
            print(f"[MICROSOFT] Checking env: client_id={bool(client_id)}, client_secret={bool(client_secret)}")
            
            if client_id and client_secret:
                import secrets
                state = secrets.token_urlsafe(32)
                
                # Microsoft OAuth scopes for Graph API
                microsoft_scopes = [
                    "openid",
                    "email", 
                    "profile",
                    "offline_access",
                    "User.Read",
                    "Mail.Read",
                    "Mail.Send",
                    "Mail.ReadWrite",
                    "Calendars.Read",
                    "Calendars.ReadWrite",
                    "Files.Read",
                    "Files.ReadWrite", 
                    "Tasks.Read",
                    "Tasks.ReadWrite",
                    "Contacts.Read",
                ]
                scope_str = "%20".join(microsoft_scopes)
                
                redirect_uri = "http://localhost:8000/oauth/callback"
                auth_url = (
                    f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&response_type=code"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                _oauth_pending_states[state] = {
                    "provider": "microsoft",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
                
                return JSONResponse({
                    "auth_url": auth_url,
                    "state": state,
                    "provider": provider,
                })
            else:
                print("⚠️ Microsoft credentials not found in .env")
                return JSONResponse({
                    "error": "Microsoft credentials not configured. Add MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET to .env",
                    "needs_setup": True,
                }, status_code=400)
        
        # For Slack, check env vars
        if provider == "slack":
            client_id = os.environ.get("SLACK_CLIENT_ID")
            client_secret = os.environ.get("SLACK_CLIENT_SECRET")
            
            print(f"[SLACK] Checking env: client_id={bool(client_id)}, client_secret={bool(client_secret)}")
            
            if client_id and client_secret:
                import secrets
                state = secrets.token_urlsafe(32)
                
                # Slack OAuth scopes
                slack_scopes = [
                    "channels:read",
                    "channels:history",
                    "chat:write",
                    "users:read",
                    "users:read.email",
                    "team:read",
                    "im:read",
                    "im:history",
                ]
                scope_str = ",".join(slack_scopes)  # Slack uses comma-separated
                
                redirect_uri = "http://localhost:8000/oauth/callback"
                auth_url = (
                    f"https://slack.com/oauth/v2/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&user_scope={scope_str}"
                    f"&state={state}"
                )
                
                _oauth_pending_states[state] = {
                    "provider": "slack",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
                
                return JSONResponse({
                    "auth_url": auth_url,
                    "state": state,
                    "provider": provider,
                })
            else:
                print("⚠️ Slack credentials not found in .env")
                return JSONResponse({
                    "error": "Slack credentials not configured. Add SLACK_CLIENT_ID and SLACK_CLIENT_SECRET to .env",
                    "needs_setup": True,
                }, status_code=400)
        
        # For GitHub, check env vars
        if provider == "github":
            client_id = os.environ.get("GITHUB_CLIENT_ID")
            client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
            
            print(f"[GITHUB] Checking env: client_id={bool(client_id)}, client_secret={bool(client_secret)}")
            
            if client_id and client_secret:
                import secrets
                state = secrets.token_urlsafe(32)
                
                # GitHub OAuth scopes
                github_scopes = ["user", "repo", "read:org"]
                scope_str = "%20".join(github_scopes)
                
                redirect_uri = "http://127.0.0.1:8000/oauth/callback"
                auth_url = (
                    f"https://github.com/login/oauth/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                _oauth_pending_states[state] = {
                    "provider": "github",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
                
                return JSONResponse({
                    "auth_url": auth_url,
                    "state": state,
                    "provider": provider,
                })
            else:
                print("⚠️ GitHub credentials not found in .env")
                return JSONResponse({
                    "error": "GitHub credentials not configured. Add GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET to .env",
                    "needs_setup": True,
                }, status_code=400)
        
        # For Spotify, check env vars  
        if provider == "spotify":
            client_id = os.environ.get("SPOTIFY_CLIENT_ID")
            client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
            
            if client_id and client_secret:
                import secrets
                state = secrets.token_urlsafe(32)
                
                spotify_scopes = [
                    "user-read-private",
                    "user-read-email",
                    "user-read-playback-state",
                    "user-modify-playback-state",
                    "user-read-currently-playing",
                    "playlist-read-private",
                    "playlist-modify-public",
                    "playlist-modify-private",
                ]
                scope_str = "%20".join(spotify_scopes)
                
                redirect_uri = "http://127.0.0.1:8000/oauth/callback"
                auth_url = (
                    f"https://accounts.spotify.com/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&response_type=code"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                _oauth_pending_states[state] = {
                    "provider": "spotify",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
                
                return JSONResponse({
                    "auth_url": auth_url,
                    "state": state,
                    "provider": provider,
                })
        
        # For other providers, use generic OAuth flow (requires client credentials setup)
        from connectors.oauth_flow import get_oauth_flow
        flow = get_oauth_flow()
        
        # Get client credentials
        store = get_cred_store()
        client_creds = store.get_client_credentials(provider)
        if not client_creds:
            return JSONResponse({
                "error": f"No client credentials configured for {provider}. Set up in /setup page.",
            }, status_code=400)
        
        scope_list = scopes.split(",") if scopes else None
        auth_url = flow.get_auth_url(
            provider=provider,
            client_id=client_creds["client_id"],
            client_secret=client_creds.get("client_secret"),
            services=scope_list,
        )
        
        return JSONResponse({
            "auth_url": auth_url,
            "provider": provider,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )

# Store pending OAuth states for callback
_oauth_pending_states: Dict[str, Any] = {}


@app.get("/oauth/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    """
    OAuth callback handler.
    
    This page is loaded in the popup window after user authorizes.
    It exchanges the code for tokens, stores them, and closes the popup.
    """
    if error:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Authorization Failed</title></head>
        <body>
            <h2>Authorization Failed</h2>
            <p>{error}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{
                        type: 'oauth_error',
                        error: '{error}'
                    }}, '*');
                }}
                setTimeout(() => window.close(), 2000);
            </script>
        </body>
        </html>
        """)
    
    if not code or not state:
        return HTMLResponse("""
        <!DOCTYPE html>
        <html>
        <head><title>Missing Parameters</title></head>
        <body>
            <h2>Missing authorization code or state</h2>
            <script>
                if (window.opener) {
                    window.opener.postMessage({
                        type: 'oauth_error',
                        error: 'Missing authorization code'
                    }, '*');
                }
                setTimeout(() => window.close(), 2000);
            </script>
        </body>
        </html>
        """)
    
    try:
        # Check for pending Google flow first
        if state in _oauth_pending_states:
            pending = _oauth_pending_states.pop(state)
            provider_used = pending["provider"]
            
            if provider_used == "google":
                # Exchange code using Google's flow
                flow = pending["flow"]
                flow.fetch_token(code=code)
                creds = flow.credentials
                
                # Store tokens using GoogleAuth
                auth = get_google_auth()
                auth._creds = creds
                auth._save_token()
                
                # Connect services with the new credentials
                global _google_calendar, _gmail_connector, _google_connected_services
                
                # Determine what scopes we got
                token_scopes = set(creds.scopes or [])
                
                # Map OAuth scopes to service names
                scope_to_service = {
                    'calendar': 'calendar',
                    'gmail': 'gmail', 
                    'mail.google': 'gmail',
                    'drive': 'drive',
                    'contacts': 'contacts',
                    'photoslibrary': 'photos',
                    'spreadsheets': 'sheets',
                    'presentations': 'slides',
                }
                
                # Clear and repopulate connected services
                _google_connected_services.clear()
                for scope in token_scopes:
                    for key, service in scope_to_service.items():
                        if key in scope.lower():
                            _google_connected_services.add(service)
                
                print(f"[OAUTH] Authorized Google services: {_google_connected_services}")
                
                has_calendar = 'calendar' in _google_connected_services
                has_gmail = 'gmail' in _google_connected_services
                
                if has_calendar:
                    _google_calendar = CalendarConnector(auth)
                    await _google_calendar.connect()
                    print("[OAUTH] Google Calendar connected!")
                
                if has_gmail:
                    from connectors.gmail import GmailConnector
                    _gmail_connector = GmailConnector(auth)
                    if await _gmail_connector.connect():
                        print("[OAUTH] Gmail connected!")
                
                # Rebuild engine
                get_telic_engine(force_rebuild=True)
                
                # Build a display of connected services
                services_display = []
                for svc in ['calendar', 'gmail', 'drive', 'contacts', 'photos', 'sheets', 'slides']:
                    if svc in _google_connected_services:
                        services_display.append(f"{svc.title()}: ✓")
                connected_text = " | ".join(services_display) if services_display else "No services"
                
                return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Authorization Successful</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                            background: #0a0a0f;
                            color: #f4f4f5;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }}
                        .card {{
                            text-align: center;
                            padding: 40px;
                        }}
                        .checkmark {{
                            font-size: 48px;
                            margin-bottom: 16px;
                        }}
                        h2 {{ margin-bottom: 8px; }}
                        p {{ color: #a1a1aa; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="checkmark">✓</div>
                        <h2>Connected!</h2>
                        <p>{connected_text}</p>
                        <p>You can close this window.</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                provider: 'google'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 1500);
                    </script>
                </body>
                </html>
                """)
            
            elif provider_used == "discord":
                # Exchange code for Discord token
                import httpx
                
                client_id = pending["client_id"]
                client_secret = pending["client_secret"]
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://discord.com/api/oauth2/token",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": "http://127.0.0.1:8000/oauth/callback",
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"Discord token exchange failed: {response.text}")
                    
                    tokens = response.json()
                
                # Store tokens
                store = get_cred_store()
                store.save_token(
                    provider="discord",
                    access_token=tokens.get("access_token"),
                    refresh_token=tokens.get("refresh_token"),
                    expires_in=tokens.get("expires_in"),
                    scopes=tokens.get("scope", "").split(),
                )
                
                print(f"[OAUTH] Discord connected!")
                
                return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Discord Connected</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                            background: #0a0a0f;
                            color: #f4f4f5;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }}
                        .card {{ text-align: center; padding: 40px; }}
                        .checkmark {{ font-size: 48px; margin-bottom: 16px; }}
                        h2 {{ margin-bottom: 8px; }}
                        p {{ color: #a1a1aa; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="checkmark">✓</div>
                        <h2>Discord Connected!</h2>
                        <p>You can close this window.</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                provider: 'discord'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 1500);
                    </script>
                </body>
                </html>
                """)
            
            elif provider_used == "microsoft":
                # Exchange code for Microsoft token
                import httpx
                
                client_id = pending["client_id"]
                client_secret = pending["client_secret"]
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": "http://localhost:8000/oauth/callback",
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"Microsoft token exchange failed: {response.text}")
                    
                    tokens = response.json()
                
                # Store tokens
                store = get_cred_store()
                store.save_token(
                    provider="microsoft",
                    access_token=tokens.get("access_token"),
                    refresh_token=tokens.get("refresh_token"),
                    expires_in=tokens.get("expires_in"),
                    scopes=tokens.get("scope", "").split(),
                )
                
                print(f"[OAUTH] Microsoft connected!")
                
                return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Microsoft Connected</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                            background: #0a0a0f;
                            color: #f4f4f5;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }}
                        .card {{ text-align: center; padding: 40px; }}
                        .checkmark {{ font-size: 48px; margin-bottom: 16px; color: #00a4ef; }}
                        h2 {{ margin-bottom: 8px; }}
                        p {{ color: #a1a1aa; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="checkmark">✓</div>
                        <h2>Microsoft Connected!</h2>
                        <p>Outlook, OneDrive, Calendar, Tasks</p>
                        <p>You can close this window.</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                provider: 'microsoft'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 1500);
                    </script>
                </body>
                </html>
                """)
            
            elif provider_used == "slack":
                # Exchange code for Slack token
                import httpx
                
                client_id = pending["client_id"]
                client_secret = pending["client_secret"]
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://slack.com/api/oauth.v2.access",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "code": code,
                            "redirect_uri": "http://localhost:8000/oauth/callback",
                        },
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"Slack token exchange failed: {response.text}")
                    
                    data = response.json()
                    if not data.get("ok"):
                        raise Exception(f"Slack error: {data.get('error')}")
                    
                    tokens = data
                
                # Store tokens - Slack user tokens come in authed_user
                store = get_cred_store()
                authed_user = tokens.get("authed_user", {})
                store.save_token(
                    provider="slack",
                    access_token=authed_user.get("access_token") or tokens.get("access_token"),
                    refresh_token=authed_user.get("refresh_token") or tokens.get("refresh_token"),
                    expires_in=None,  # Slack tokens don't expire
                    scopes=(authed_user.get("scope", "") or tokens.get("scope", "")).split(","),
                )
                
                team_name = tokens.get("team", {}).get("name", "Workspace")
                print(f"[OAUTH] Slack connected to {team_name}!")
                
                return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Slack Connected</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                            background: #0a0a0f;
                            color: #f4f4f5;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }}
                        .card {{ text-align: center; padding: 40px; }}
                        .checkmark {{ font-size: 48px; margin-bottom: 16px; color: #4a154b; }}
                        h2 {{ margin-bottom: 8px; }}
                        p {{ color: #a1a1aa; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="checkmark">✓</div>
                        <h2>Slack Connected!</h2>
                        <p>Workspace: {team_name}</p>
                        <p>You can close this window.</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                provider: 'slack'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 1500);
                    </script>
                </body>
                </html>
                """)
            
            elif provider_used == "github":
                # Exchange code for GitHub token
                import httpx
                
                client_id = pending["client_id"]
                client_secret = pending["client_secret"]
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://github.com/login/oauth/access_token",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "code": code,
                        },
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "application/json",
                        },
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"GitHub token exchange failed: {response.text}")
                    
                    tokens = response.json()
                    if "error" in tokens:
                        raise Exception(f"GitHub error: {tokens.get('error_description', tokens.get('error'))}")
                
                # Store tokens
                store = get_cred_store()
                store.save_token(
                    provider="github",
                    access_token=tokens.get("access_token"),
                    refresh_token=tokens.get("refresh_token"),
                    expires_in=tokens.get("expires_in"),
                    scopes=tokens.get("scope", "").split(","),
                )
                
                print(f"[OAUTH] GitHub connected!")
                
                return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>GitHub Connected</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                            background: #0a0a0f;
                            color: #f4f4f5;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }}
                        .card {{ text-align: center; padding: 40px; }}
                        .checkmark {{ font-size: 48px; margin-bottom: 16px; }}
                        h2 {{ margin-bottom: 8px; }}
                        p {{ color: #a1a1aa; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="checkmark">✓</div>
                        <h2>GitHub Connected!</h2>
                        <p>Repos, Issues, PRs</p>
                        <p>You can close this window.</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                provider: 'github'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 1500);
                    </script>
                </body>
                </html>
                """)
            
            elif provider_used == "spotify":
                # Exchange code for Spotify token
                import httpx
                import base64
                
                client_id = pending["client_id"]
                client_secret = pending["client_secret"]
                auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
                
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://accounts.spotify.com/api/token",
                        data={
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": "http://127.0.0.1:8000/oauth/callback",
                        },
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Authorization": f"Basic {auth_header}",
                        },
                    )
                    
                    if response.status_code != 200:
                        raise Exception(f"Spotify token exchange failed: {response.text}")
                    
                    tokens = response.json()
                
                # Store tokens
                store = get_cred_store()
                store.save_token(
                    provider="spotify",
                    access_token=tokens.get("access_token"),
                    refresh_token=tokens.get("refresh_token"),
                    expires_in=tokens.get("expires_in"),
                    scopes=tokens.get("scope", "").split(),
                )
                
                print(f"[OAUTH] Spotify connected!")
                
                return HTMLResponse(f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Spotify Connected</title>
                    <style>
                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                            background: #0a0a0f;
                            color: #f4f4f5;
                            display: flex;
                            align-items: center;
                            justify-content: center;
                            height: 100vh;
                            margin: 0;
                        }}
                        .card {{ text-align: center; padding: 40px; }}
                        .checkmark {{ font-size: 48px; margin-bottom: 16px; color: #1db954; }}
                        h2 {{ margin-bottom: 8px; }}
                        p {{ color: #a1a1aa; }}
                    </style>
                </head>
                <body>
                    <div class="card">
                        <div class="checkmark">✓</div>
                        <h2>Spotify Connected!</h2>
                        <p>Music playback enabled</p>
                        <p>You can close this window.</p>
                    </div>
                    <script>
                        if (window.opener) {{
                            window.opener.postMessage({{
                                type: 'oauth_success',
                                provider: 'spotify'
                            }}, '*');
                        }}
                        setTimeout(() => window.close(), 1500);
                    </script>
                </body>
                </html>
                """)
        
        # Fallback to generic OAuth flow for other providers
        from connectors.oauth_flow import get_oauth_flow
        
        flow = get_oauth_flow()
        tokens = await flow.handle_callback(code, state)
        
        if not tokens:
            raise Exception("Failed to exchange authorization code")
        
        provider_used = tokens.get("provider", "unknown")
        
        # Store tokens
        store = get_cred_store()
        store.save_token(
            provider=provider_used,
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            expires_in=tokens.get("expires_in"),
            scopes=tokens.get("scope", "").split() if tokens.get("scope") else [],
        )
        
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authorization Successful</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, sans-serif;
                    background: #0a0a0f;
                    color: #f4f4f5;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    height: 100vh;
                    margin: 0;
                }}
                .card {{
                    text-align: center;
                    padding: 40px;
                }}
                .checkmark {{
                    font-size: 48px;
                    margin-bottom: 16px;
                }}
                h2 {{ margin-bottom: 8px; }}
                p {{ color: #a1a1aa; }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="checkmark">✓</div>
                <h2>Connected!</h2>
                <p>You can close this window.</p>
            </div>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{
                        type: 'oauth_success',
                        provider: '{provider_used}'
                    }}, '*');
                }}
                setTimeout(() => window.close(), 1500);
            </script>
        </body>
        </html>
        """)
        
    except Exception as e:
        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html>
        <head><title>Authorization Failed</title></head>
        <body style="font-family: sans-serif; padding: 40px;">
            <h2>Authorization Failed</h2>
            <p>{str(e)}</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage({{
                        type: 'oauth_error',
                        error: '{str(e)}'
                    }}, '*');
                }}
                setTimeout(() => window.close(), 3000);
            </script>
        </body>
        </html>
        """)


# Routes
@app.get("/")
async def root():
    """Serve the UI with no-cache headers so updates are always picked up."""
    return FileResponse(
        Path(__file__).parent / "ui" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def resolve_wire_value(val, read_results: dict, primitive_to_step: dict):
    """
    Resolve wire references in a value. Handles multiple formats:
    - step_N.path (e.g., step_0.results[0].email)
    - {{PRIMITIVE.operation.path}} (e.g., {{CONTACTS.search.results[0].email}})
    - Inline placeholders within strings
    """
    if not isinstance(val, str):
        return val
    
    import re
    
    def follow_path(data, path):
        """Navigate a path like 'results[0].email' through data."""
        if data is None:
            return None
        current = data
        # Split on dots, but handle brackets
        parts = re.split(r'\.(?![^\[]*\])', path)
        for part in parts:
            if current is None:
                return None
            # Handle array index like results[0]
            bracket_match = re.match(r'(\w+)\[(\d+)\]', part)
            if bracket_match:
                key, idx = bracket_match.groups()
                if isinstance(current, dict) and key in current:
                    current = current[key]
                    if isinstance(current, list) and int(idx) < len(current):
                        current = current[int(idx)]
                    else:
                        return None
                else:
                    return None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
    
    # Check for {{PRIMITIVE.operation.path}} format (can be multiple in string)
    def replace_placeholder(match):
        placeholder = match.group(1)  # e.g., "CONTACTS.search.results[0].email"
        parts = placeholder.split('.', 2)  # Split into [PRIMITIVE, operation, path]
        if len(parts) >= 2:
            prim_op = f"{parts[0]}.{parts[1]}".upper()
            step_id = primitive_to_step.get(prim_op)
            if step_id is not None and step_id in read_results:
                if len(parts) > 2:
                    result = follow_path(read_results[step_id], parts[2])
                else:
                    result = read_results[step_id]
                if result is not None:
                    return str(result) if not isinstance(result, str) else result
        return match.group(0)  # Keep original if can't resolve
    
    # Replace all {{...}} placeholders
    if '{{' in val:
        resolved = re.sub(r'\{\{([^}]+)\}\}', replace_placeholder, val)
        return resolved
    
    # Check for step_N.path format
    step_match = re.match(r'step_(\d+)\.(.+)', val)
    if step_match:
        step_id = int(step_match.group(1))
        path = step_match.group(2)
        if step_id in read_results:
            result = follow_path(read_results[step_id], path)
            if result is not None:
                return result
    
    return val


def has_side_effect(step):
    """Check if step has side effects (needs approval). AI decides via side_effect field."""
    return getattr(step, 'side_effect', True)  # Default to true (safer)


@app.post("/chat")
async def chat(req: ChatRequest):
    """
    Main chat endpoint with conversation memory.
    
    Flow:
    1. Add message to conversation history
    2. If pending clarification, go straight to planner
    3. Otherwise, check intent then plan
    4. Auto-run read-only steps
    5. Show write steps for approval
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
        
        # Check if this is a response to a clarification question
        # (previous assistant message exists and had no plan = was a question)
        is_clarification_response = False
        if len(_conversation_history) >= 2:
            # Look for pattern: user asked something, assistant asked clarifying question, user responded
            for i in range(len(_conversation_history) - 2, -1, -1):
                msg = _conversation_history[i]
                if msg["role"] == "assistant":
                    # If assistant's last message looks like a question, treat current as continuation
                    if "?" in msg["content"]:
                        is_clarification_response = True
                    break
        
        # Build context string from recent conversation
        context_str = ""
        if len(_conversation_history) > 1:
            context_str = "Recent conversation:\n"
            for msg in _conversation_history[:-1]:  # Exclude current message
                role = "User" if msg["role"] == "user" else "Assistant"
                context_str += f"{role}: {msg['content']}\n"
            context_str += "\nCurrent request:\n"
        
        # If this is a clarification response, skip intent detection and go straight to action
        if is_clarification_response:
            print(f"[CHAT] Clarification response detected, skipping intent check")
            needs_action = True
            response_text = "Processing your request..."
        else:
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
                
                # Build mapping: primitive.operation -> step_id for wire resolution
                primitive_to_step = {}
                for step in exec_result.plan:
                    key = f"{step.primitive}.{step.operation}".upper()
                    primitive_to_step[key] = step.id
                    # Also map with common aliases
                    primitive_to_step[f"{step.primitive}.SEARCH".upper()] = step.id
                
                for step in exec_result.plan:
                    if not has_side_effect(step):  # AI says no side effects = safe to auto-run
                        print(f"[CHAT] Auto-running read-only: {step.primitive}.{step.operation}")
                        try:
                            # Resolve any wire references from previous steps
                            resolved_params = dict(step.params)
                            for key, val in step.params.items():
                                resolved_params[key] = resolve_wire_value(val, read_results, primitive_to_step)
                            
                            # Execute - handle PRIMITIVE.OPERATION format
                            prim_name = step.primitive.upper()
                            op_name = step.operation
                            if "." in prim_name:
                                parts = prim_name.split(".", 1)
                                prim_name = parts[0]
                                op_name = op_name or parts[1].lower()
                            
                            primitive = engine._primitives.get(prim_name)
                            if primitive:
                                step_result = await primitive.execute(op_name, resolved_params)
                                read_results[step.id] = step_result
                                # Extract actual data from StepResult if needed
                                result_data = step_result.data if hasattr(step_result, 'data') else step_result
                                completed_steps.append({
                                    "id": step.id,
                                    "description": step.description,
                                    "primitive": prim_name,
                                    "operation": op_name,
                                    "status": "completed",
                                    "result_summary": str(result_data)[:500] if result_data else None
                                })
                                print(f"[CHAT]   Got: {str(result_data)[:200]}")
                            else:
                                print(f"[CHAT]   Unknown primitive: {prim_name}")
                                completed_steps.append({
                                    "id": step.id,
                                    "description": step.description,
                                    "primitive": prim_name,
                                    "operation": op_name,
                                    "status": "failed",
                                    "error": f"Unknown primitive: {prim_name}"
                                })
                        except Exception as e:
                            import traceback
                            traceback.print_exc()
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
                            resolved_params[key] = resolve_wire_value(val, read_results, primitive_to_step)
                        
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


# ============================================================
#  REACT AGENT ENDPOINTS (New, clean implementation)
# ============================================================

class ReactRequest(BaseModel):
    message: str


class ReactApproveRequest(BaseModel):
    approved: bool


def serialize_result(result: Any) -> Any:
    """Convert any result to JSON-serializable form."""
    if result is None:
        return None
    if isinstance(result, (str, int, float, bool)):
        return result
    if isinstance(result, (list, tuple)):
        return [serialize_result(item) for item in result]
    if isinstance(result, dict):
        return {k: serialize_result(v) for k, v in result.items()}
    # Handle dataclasses and objects with __dict__
    if hasattr(result, '__dict__'):
        return serialize_result(vars(result))
    # Fallback to string representation
    return str(result)


def step_to_dict(step: Step) -> Dict[str, Any]:
    """Convert a Step to a JSON-serializable dict."""
    return {
        "tool": step.tool_call.name,
        "params": step.tool_call.params,
        "status": step.status.value,
        "result": serialize_result(step.result),
        "error": step.error,
        "requires_approval": step.requires_approval,
    }


def state_to_response(state: AgentState) -> Dict[str, Any]:
    """Convert AgentState to API response."""
    return {
        "steps": [step_to_dict(s) for s in state.steps],
        "pending_approval": step_to_dict(state.pending_approval) if state.pending_approval else None,
        "is_complete": state.is_complete,
        "response": state.final_response,
    }


async def select_primitives_for_request(message: str, all_primitives: dict) -> dict:
    """
    DEPRECATED: Dynamic primitive selection caused conversation context issues.
    Now we use all primitives and let the LLM choose which to use.
    Keeping this function for potential future use with smarter filtering.
    """
    return all_primitives


def get_session_agent(force_new: bool = False) -> Optional[ReActAgent]:
    """
    Get or create a session-persistent ReAct agent.
    
    Unlike the old approach that created fresh agents per request,
    this maintains conversation context like ChatGPT/Gemini.
    """
    global _session_agent, _session_messages
    
    if force_new:
        _session_agent = None
        _session_messages = []
    
    if _session_agent is not None:
        return _session_agent
    
    # Need API key
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    
    # Get the Telic engine
    engine = get_telic_engine()
    if not engine:
        return None
    
    # Use ALL primitives - let the LLM decide what's relevant
    tools = primitives_to_tools(engine._primitives)
    print(f"[SESSION] Created agent with {len(tools)} tools")
    
    # Create LLM client
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        llm_client = anthropic.Anthropic()
    else:
        import openai
        llm_client = openai.OpenAI()
    
    from datetime import datetime, timedelta
    now = datetime.now()
    # Build date context with upcoming days for accurate scheduling
    date_context = f"""TODAY: {now.strftime("%A, %B %d, %Y")} ({now.strftime("%Y-%m-%d")})
This week:
"""
    for i in range(7):
        d = now + timedelta(days=i)
        date_context += f"  {d.strftime('%A %b %d')}: {d.strftime('%Y-%m-%d')}\n"
    
    system_prompt = f"""You are Ziggy, an AI assistant that helps users get things done.

{date_context}

You have access to the user's email, calendar, files, tasks, and other services.
Use tools to accomplish what the user asks. You can call multiple tools in parallel when the calls are independent.

Be efficient — don't repeat searches with slight variations. If a search returns no results, broaden the query or try a different approach rather than retrying similar queries.

CONVERSATION CONTEXT:
- You have full memory of this conversation session
- References like "the first one", "send it", "the information above" refer to earlier in THIS conversation
- If user mentions something from earlier, use that context

IMPORTANT BEHAVIORS:
- When you find multiple matches, ask user which one they want
- When information is missing, ask before guessing
- Be conversational - explain what you're doing

When complete, summarize what was done."""
    
    _session_agent = ReActAgent(
        llm_client=llm_client,
        tools=tools,
        system_prompt=system_prompt,
    )
    
    return _session_agent


@app.post("/react/chat")
async def react_chat(req: ReactRequest):
    """
    Main chat endpoint - continues the current session.
    
    Unlike before, this ALWAYS continues the same conversation session.
    Use /react/new to start a fresh conversation.
    """
    global _react_state, _session_messages, _session_agent
    
    agent = get_session_agent()
    if not agent:
        return JSONResponse({
            "error": "No API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.",
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": None,
        })
    
    try:
        # Ensure we have a session ID
        if not _session_id:
            _session_id = session_store.new_session_id()
        
        print(f"[SESSION] User: {req.message[:80]}...")
        print(f"[SESSION] Conversation history: {len(_session_messages)} messages")
        
        # Build context from conversation history for the agent
        if _session_messages:
            # Summarize recent conversation for context
            context_lines = []
            for m in _session_messages[-10:]:  # Last 10 messages
                role = 'User' if m['role'] == 'user' else 'Assistant'
                content = m['content'][:300] + "..." if len(m['content']) > 300 else m['content']
                context_lines.append(f"{role}: {content}")
            context_summary = "\n".join(context_lines)
            
            full_message = f"""[CONVERSATION CONTEXT - This is a continuation of an ongoing conversation]
Previous messages in this session:
{context_summary}

[CURRENT USER MESSAGE]
{req.message}

Remember: References like "the first one", "send it to him", "the information above" refer to the context above."""
        else:
            full_message = req.message
        
        # Run the agent with context
        state = await agent.run(full_message)
        _react_state = state
        
        # Record in session history
        _session_messages.append({"role": "user", "content": req.message})
        if state.final_response:
            _session_messages.append({"role": "assistant", "content": state.final_response})
        
        # Auto-save session
        _auto_save_session()
        
        # Log what happened
        for step in state.steps:
            status = "✓" if step.status == StepStatus.COMPLETED else "⏸" if step.status == StepStatus.PENDING_APPROVAL else "✗"
            print(f"[SESSION] {status} {step.tool_call.name}")
        
        if state.pending_approval:
            print(f"[SESSION] Waiting for approval: {state.pending_approval.tool_call.name}")
        
        if state.is_complete:
            print(f"[SESSION] Complete: {state.final_response[:80] if state.final_response else 'No response'}...")
        
        return JSONResponse(state_to_response(state))
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": f"Error: {str(e)}",
        })


@app.post("/react/chat/stream")
async def react_chat_stream(req: ReactRequest):
    """
    Streaming chat endpoint using Server-Sent Events.
    
    Streams step-by-step progress as the agent works,
    so the UI can show real-time activity instead of waiting.
    """
    import json
    global _react_state, _session_messages, _session_id

    # Ensure we have a session ID
    if not _session_id:
        _session_id = session_store.new_session_id()

    agent = get_session_agent()
    if not agent:
        async def err():
            yield f"data: {json.dumps({'event': 'error', 'message': 'No API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY.'})}\n\n"
        return StreamingResponse(err(), media_type="text/event-stream")

    # Build message with conversation context (same logic as react_chat)
    print(f"[STREAM] User: {req.message[:80]}...")
    print(f"[STREAM] Conversation history: {len(_session_messages)} messages")

    if _session_messages:
        context_lines = []
        for m in _session_messages[-10:]:
            role = 'User' if m['role'] == 'user' else 'Assistant'
            content = m['content'][:300] + "..." if len(m['content']) > 300 else m['content']
            context_lines.append(f"{role}: {content}")
        context_summary = "\n".join(context_lines)

        full_message = f"""[CONVERSATION CONTEXT - This is a continuation of an ongoing conversation]
Previous messages in this session:
{context_summary}

[CURRENT USER MESSAGE]
{req.message}

Remember: References like "the first one", "send it to him", "the information above" refer to the context above."""
    else:
        full_message = req.message

    # Event queue for SSE
    queue = asyncio.Queue()

    async def on_step(step: Step):
        """Push step events to SSE queue."""
        data = step_to_dict(step)
        data["id"] = step.tool_call.id  # Unique ID for matching start/complete
        if step.status == StepStatus.RUNNING:
            await queue.put({"event": "tool_start", "step": data})
        elif step.status == StepStatus.COMPLETED:
            await queue.put({"event": "tool_complete", "step": data})
        elif step.status == StepStatus.FAILED:
            await queue.put({"event": "tool_failed", "step": data})
        elif step.status == StepStatus.PENDING_APPROVAL:
            await queue.put({"event": "approval_needed", "step": data})

    async def on_thinking():
        await queue.put({"event": "thinking"})

    # Wire callbacks (save previous to restore later)
    prev_on_step = agent.on_step
    prev_on_thinking = getattr(agent, 'on_thinking', None)
    agent.on_step = on_step
    agent.on_thinking = on_thinking

    async def event_generator():
        global _react_state

        # Initial thinking event
        yield f"data: {json.dumps({'event': 'thinking'})}\n\n"

        # Run agent as background task
        task = asyncio.create_task(agent.run(full_message))

        try:
            while not task.done():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"

            # Drain remaining queued events
            while not queue.empty():
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"

            # Final state
            state = task.result()
            _react_state = state

            # Update session history
            _session_messages.append({"role": "user", "content": req.message})
            if state.final_response:
                _session_messages.append({"role": "assistant", "content": state.final_response})

            # Auto-save session
            _auto_save_session()

            # Log
            for s in state.steps:
                icon = "✓" if s.status == StepStatus.COMPLETED else "⏸" if s.status == StepStatus.PENDING_APPROVAL else "✗"
                print(f"[STREAM] {icon} {s.tool_call.name}")
            if state.is_complete:
                print(f"[STREAM] Complete: {state.final_response[:80] if state.final_response else 'No response'}...")

            yield f"data: {json.dumps({'event': 'complete', 'data': state_to_response(state)})}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
        finally:
            agent.on_step = prev_on_step
            agent.on_thinking = prev_on_thinking

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/react/new")
async def react_new_conversation():
    """Start a fresh conversation - saves current session, then clears."""
    global _session_messages, _session_agent, _react_state, _session_id
    
    # Auto-save current session if it has messages
    if _session_id and _session_messages:
        _auto_save_session()
    
    _session_messages = []
    _session_agent = None
    _react_state = None
    _session_id = session_store.new_session_id()
    print(f"[SESSION] Started new conversation: {_session_id}")
    return JSONResponse({"status": "ok", "message": "New conversation started", "session_id": _session_id})


@app.post("/react/approve")
async def react_approve(req: ReactApproveRequest):
    """
    Approve or reject a pending action.
    
    After approval, the agent continues executing.
    """
    global _react_state, _session_messages
    
    agent = get_session_agent()
    if not agent or not _react_state:
        return JSONResponse({
            "error": "No pending action",
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": None,
        })
    
    try:
        action = "Approved" if req.approved else "Rejected"
        if _react_state.pending_approval:
            print(f"[SESSION] {action}: {_react_state.pending_approval.tool_call.name}")
        
        # Continue with approval decision
        state = await agent.continue_with_approval(req.approved)
        _react_state = state
        
        # Record result in session history
        if state.final_response:
            _session_messages.append({"role": "assistant", "content": state.final_response})
        
        return JSONResponse(state_to_response(state))
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse({
            "error": str(e),
            "steps": [],
            "pending_approval": None,
            "is_complete": True,
            "response": f"Error: {str(e)}",
        })


# /react/continue is now deprecated - /react/chat handles all messages with session context
@app.post("/react/continue")
async def react_continue(req: ReactRequest):
    """
    DEPRECATED: Use /react/chat instead.
    Redirects to /react/chat for backwards compatibility.
    """
    return await react_chat(req)
    return await react_chat(req)


# ==========================================================
# Session History - save, list, load, delete past conversations
# ==========================================================

def _auto_save_session():
    """Save the current session to SQLite. Call before clearing."""
    global _session_id
    if not _session_id or not _session_messages:
        return
    # Generate title from first user message
    title = "Untitled"
    for m in _session_messages:
        if m["role"] == "user":
            title = m["content"][:80].strip()
            break
    session_store.save_session(_session_id, title, _session_messages)
    print(f"[SESSION] Auto-saved session {_session_id}: {title[:50]}")


@app.get("/sessions")
async def list_sessions(limit: int = 50):
    """List all saved sessions, most recent first."""
    return JSONResponse(session_store.list_sessions(limit))


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Get a saved session with its full message history."""
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(session)


@app.post("/sessions/{session_id}/load")
async def load_session(session_id: str):
    """Load a saved session as the active conversation."""
    global _session_id, _session_messages, _session_agent, _react_state
    
    # Save current session first if it has messages
    if _session_id and _session_messages:
        _auto_save_session()
    
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    _session_id = session_id
    _session_messages = session["messages"]
    _session_agent = None  # Force agent recreation to pick up new context
    _react_state = None
    print(f"[SESSION] Loaded session {session_id} with {len(_session_messages)} messages")
    return JSONResponse({"status": "ok", "session": session})


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a saved session."""
    deleted = session_store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse({"status": "ok"})


@app.post("/clear")
async def clear_conversation():
    """Clear conversation history to start fresh."""
    global _conversation_history, _react_state, _react_agent, _session_messages, _session_agent
    _conversation_history = []
    _react_state = None
    _react_agent = None
    _session_messages = []
    _session_agent = None
    print("[SESSION] Cleared all conversation state")
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
                
                # Handle PRIMITIVE.OPERATION format (e.g., "DOCUMENT.CREATE" -> "DOCUMENT" + "create")
                if "." in prim_name:
                    parts = prim_name.split(".", 1)
                    prim_name = parts[0]
                    op = op or parts[1].lower()
                
                # Skip CLARIFY - it's a signal, not a real primitive
                if prim_name == "CLARIFY":
                    continue
                
                print(f"[EXECUTE]   Running {prim_name}.{op} with params: {params}")
                
                primitive = engine._primitives.get(prim_name)
                if primitive:
                    try:
                        result = await primitive.execute(op, params)
                        # Extract .data from StepResult for proper serialization
                        result_data = result.data if hasattr(result, 'data') else result
                        step_results.append({
                            "id": ws["id"],
                            "description": ws["description"],
                            "primitive": prim_name,
                            "operation": op,
                            "success": True,
                            "data": result_data if isinstance(result_data, (dict, list, str, int, float, bool, type(None))) else str(result_data),
                            "error": None,
                        })
                        print(f"[EXECUTE]   Success: {str(result_data)[:200]}")
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
            
            # Check if plan contains CLARIFY - this isn't an error, just needs more info
            if exec_result.plan and len(exec_result.plan) > 0 and exec_result.plan[0].primitive == "CLARIFY":
                question = exec_result.plan[0].params.get("question", exec_result.plan[0].description)
                return JSONResponse({
                    "error": None,
                    "success": True,
                    "results": [],
                    "final_result": None,
                    "clarify": question,
                    "summary": "Need more information",
                })
        
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
                    
                    # Skip CLARIFY - it's a signal, not a real primitive
                    if prim_name == "CLARIFY":
                        continue
                    
                    primitive = engine._primitives.get(prim_name)
                    if primitive:
                        try:
                            result = await primitive.execute(op, params)
                            # Extract .data from StepResult for JSON serialization
                            result_data = result.data if hasattr(result, 'data') else result
                            await step_callback(ws["id"], ws["description"], prim_name, op, True, result_data, None)
                            step_results.append({"success": True, "data": result_data})
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
                # First check if this is a clarification request
                exec_result = await engine.do(
                    req.message, 
                    require_approval=False,
                    on_step_complete=step_callback,
                )
                
                # Check if plan contains CLARIFY - this isn't an error, it's asking for input
                if exec_result.plan and len(exec_result.plan) > 0 and exec_result.plan[0].primitive == "CLARIFY":
                    question = exec_result.plan[0].params.get("question", exec_result.plan[0].description)
                    await queue.put({
                        "type": "clarify",
                        "question": question,
                        "success": True,
                    })
                    return
                
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
        "running": monitor._state.value == "running",
        "stats": monitor.get_stats(),
    })


@app.post("/intelligence/monitor/stop")
async def stop_monitoring():
    """Stop the proactive monitoring loop."""
    monitor = get_proactive_monitor()
    await monitor.stop()
    return JSONResponse({
        "running": monitor._state.value == "running",
        "stats": monitor.get_stats(),
    })


@app.get("/intelligence/monitor/status")
async def monitor_status():
    """Get monitoring status."""
    monitor = get_proactive_monitor()
    return JSONResponse({
        "running": monitor._state.value == "running",
        "paused": monitor._state.value == "paused",
        "stats": monitor.get_stats(),
        "connected_services": list(monitor._service_adapters.keys()),
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
    """Connect to Google Calendar and Gmail via OAuth."""
    global _google_calendar, _gmail_connector, _telic_engine
    
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
        # This opens a browser for OAuth - request both calendar and gmail scopes
        print("[GOOGLE] Starting OAuth flow...")
        creds = await auth.get_credentials(['calendar', 'gmail'])
        
        if not creds:
            return JSONResponse({
                "success": False,
                "error": "OAuth flow failed or was cancelled",
            })
        
        # Create and connect the calendar connector
        _google_calendar = CalendarConnector(auth)
        await _google_calendar.connect()
        
        # Also connect Gmail
        try:
            from connectors.gmail import GmailConnector
            _gmail_connector = GmailConnector(auth)
            if await _gmail_connector.connect():
                print("[GOOGLE] Gmail connected!")
            else:
                print("[GOOGLE] Gmail connection failed")
                _gmail_connector = None
        except Exception as gmail_err:
            print(f"[GOOGLE] Gmail init failed: {gmail_err}")
            _gmail_connector = None
        
        # Rebuild the engine with the new connectors
        _telic_engine = None
        get_telic_engine(force_rebuild=True)
        
        # List calendars to confirm connection
        calendars = await _google_calendar.list_calendars()
        
        print(f"[GOOGLE] Connected! Found {len(calendars)} calendars")
        
        return JSONResponse({
            "success": True,
            "calendars": calendars,
            "gmail_connected": _gmail_connector is not None,
            "message": f"Connected to Google Calendar. Found {len(calendars)} calendars." + 
                      (" Gmail also connected." if _gmail_connector else " Gmail not connected."),
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


# ============================================================================
# CONNECTOR REGISTRY ENDPOINTS
# ============================================================================

@app.get("/connectors")
async def list_connectors():
    """List all registered connectors and their status."""
    registry = get_registry()
    credential_store = get_credential_store()
    
    connectors = []
    for metadata in registry.list_connectors():
        # Check connection status from credential store
        has_credentials = credential_store.has(metadata.provider)
        is_connected = credential_store.has_valid(metadata.provider)
        
        connectors.append({
            "name": metadata.name,
            "display_name": metadata.display_name,
            "provider": metadata.provider,
            "primitives": metadata.primitives,
            "description": metadata.description,
            "icon": metadata.icon,
            "setup_url": metadata.setup_url,
            "has_credentials": has_credentials,
            "is_connected": is_connected,
            "requires_client_creds": metadata.requires_client_creds,
        })
    
    return JSONResponse({
        "connectors": connectors,
        "total": len(connectors),
        "connected": len([c for c in connectors if c["is_connected"]]),
    })


@app.get("/connectors/providers")
async def list_providers():
    """List all providers and their connectors."""
    registry = get_registry()
    credential_store = get_credential_store()
    
    providers = {}
    for provider in registry.get_providers():
        connectors = registry.get_connectors_for_provider(provider)
        has_credentials = credential_store.has(provider)
        is_connected = credential_store.has_valid(provider)
        
        providers[provider] = {
            "connectors": connectors,
            "has_credentials": has_credentials,
            "is_connected": is_connected,
            "setup_instructions": registry.get_setup_instructions(provider),
        }
    
    return JSONResponse({
        "providers": providers,
        "connected": registry.get_connected_providers(),
    })


@app.get("/connectors/primitives")
async def list_primitives_with_connectors():
    """List all primitives and their available connectors."""
    registry = get_registry()
    
    primitives = registry.get_available_primitives()
    
    return JSONResponse({
        "primitives": {
            name: {
                "connectors": connectors,
                "preferred": registry.get_preferred_connector(name),
            }
            for name, connectors in primitives.items()
        }
    })


@app.get("/connectors/{connector_name}/status")
async def get_connector_status(connector_name: str):
    """Get detailed status for a specific connector."""
    registry = get_registry()
    credential_store = get_credential_store()
    
    metadata = registry.get_metadata(connector_name)
    if not metadata:
        raise HTTPException(status_code=404, detail=f"Connector not found: {connector_name}")
    
    status = registry.get_status(connector_name)
    credentials = credential_store.get(metadata.provider)
    
    return JSONResponse({
        "name": metadata.name,
        "display_name": metadata.display_name,
        "provider": metadata.provider,
        "primitives": metadata.primitives,
        "status": status.status.value if status else "disconnected",
        "last_check": status.last_check.isoformat() if status and status.last_check else None,
        "error": status.error_message if status else None,
        "has_credentials": credentials is not None,
        "credentials_expired": credentials.is_expired() if credentials else None,
        "scopes": credentials.scopes if credentials else [],
    })


class SetPreferenceRequest(BaseModel):
    primitive: str
    connector: str


@app.post("/connectors/preference")
async def set_connector_preference(req: SetPreferenceRequest):
    """Set the preferred connector for a primitive."""
    registry = get_registry()
    
    success = registry.set_preferred_connector(req.primitive, req.connector)
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot set {req.connector} as preferred for {req.primitive}"
        )
    
    return JSONResponse({
        "success": True,
        "primitive": req.primitive,
        "preferred_connector": req.connector,
    })


@app.get("/connectors/setup-status")
async def get_setup_status():
    """Get which connectors are ready and which need setup."""
    registry = get_registry()
    return JSONResponse(registry.get_setup_status())


@app.get("/connectors/{provider}/instructions")
async def get_setup_instructions(provider: str):
    """Get setup instructions for a provider."""
    registry = get_registry()
    return JSONResponse({
        "provider": provider,
        "instructions": registry.get_setup_instructions(provider),
    })


# ============================================================================
# OAUTH FLOW ENDPOINTS (Phase 2)
# ============================================================================

class OAuthInitRequest(BaseModel):
    """Request to start OAuth flow."""
    client_id: str
    client_secret: str | None = None
    services: list[str] | None = None  # e.g., ["gmail", "calendar"] for Google
    scopes: list[str] | None = None    # Custom scopes
    redirect_uri: str | None = None


@app.get("/oauth/providers")
async def list_oauth_providers():
    """List all supported OAuth providers."""
    oauth = get_oauth_flow()
    
    providers = {}
    for name in oauth.get_supported_providers():
        info = oauth.get_provider_info(name)
        providers[name] = info
    
    return JSONResponse({
        "providers": providers,
        "count": len(providers),
    })


@app.get("/oauth/status")
async def get_oauth_status():
    """Get connection status for all OAuth providers."""
    oauth = get_oauth_flow()
    status = oauth.get_connection_status()
    
    connected = [p for p, s in status.items() if s["connected"]]
    
    return JSONResponse({
        "status": status,
        "connected": connected,
        "total_connected": len(connected),
    })


@app.post("/oauth/{provider}/init")
async def init_provider_oauth(provider: str, req: OAuthInitRequest):
    """
    Start OAuth flow for a provider.
    
    Returns an authorization URL to redirect the user to.
    The user will grant permissions, then be redirected back to /oauth/callback.
    
    Example:
        POST /oauth/google/init
        {
            "client_id": "your-client-id.apps.googleusercontent.com",
            "client_secret": "your-client-secret",
            "services": ["gmail", "calendar", "drive"]
        }
    
    Response:
        {
            "auth_url": "https://accounts.google.com/o/oauth2/....",
            "provider": "google",
            "services": ["gmail", "calendar", "drive"]
        }
    """
    oauth = get_oauth_flow()
    
    # Validate provider
    if provider not in oauth.get_supported_providers():
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider: {provider}. Supported: {oauth.get_supported_providers()}"
        )
    
    try:
        auth_url = oauth.get_auth_url(
            provider=provider,
            client_id=req.client_id,
            client_secret=req.client_secret,
            services=req.services,
            scopes=req.scopes,
            redirect_uri=req.redirect_uri,
        )
        
        return JSONResponse({
            "auth_url": auth_url,
            "provider": provider,
            "services": req.services or [],
            "message": f"Redirect user to auth_url to authorize {provider}",
        })
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/oauth/callback")
async def oauth_callback_get(code: str, state: str):
    """
    OAuth callback endpoint (GET).
    
    This is where OAuth providers redirect after user authorization.
    Returns a success HTML page.
    """
    oauth = get_oauth_flow()
    
    try:
        result = await oauth.handle_callback(code, state)
        
        # Return success page
        html_path = Path(__file__).parent / "ui" / "oauth_success.html"
        if html_path.exists():
            return FileResponse(html_path)
        
        # Fallback HTML if file doesn't exist
        return JSONResponse({
            "success": True,
            "provider": result["provider"],
            "services": result["services"],
            "message": "Successfully connected! You can close this window.",
        })
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(status_code=500, detail=f"OAuth error: {str(e)}")


@app.post("/oauth/callback")
async def oauth_callback_post(code: str, state: str):
    """
    OAuth callback endpoint (POST).
    
    Alternative for programmatic OAuth completion.
    """
    oauth = get_oauth_flow()
    
    try:
        result = await oauth.handle_callback(code, state)
        
        return JSONResponse({
            "success": True,
            "provider": result["provider"],
            "services": result["services"],
            "scopes": result["scopes"],
        })
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/oauth/{provider}/status")
async def get_provider_oauth_status(provider: str):
    """Get OAuth connection status for a specific provider."""
    oauth = get_oauth_flow()
    
    if provider not in oauth.get_supported_providers():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    
    status = oauth.get_connection_status()
    provider_status = status.get(provider, {"connected": False})
    
    return JSONResponse({
        "provider": provider,
        **provider_status,
    })


@app.post("/oauth/{provider}/refresh")
async def refresh_provider_token(provider: str):
    """Refresh OAuth token for a provider."""
    oauth = get_oauth_flow()
    
    if provider not in oauth.get_supported_providers():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    
    try:
        success = await oauth.refresh_token(provider)
        
        return JSONResponse({
            "success": success,
            "provider": provider,
            "message": "Token refreshed" if success else "Token refresh failed",
        })
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/oauth/{provider}")
async def disconnect_provider(provider: str):
    """Disconnect and remove credentials for a provider."""
    oauth = get_oauth_flow()
    
    if provider not in oauth.get_supported_providers():
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    
    success = oauth.disconnect(provider)
    
    return JSONResponse({
        "success": success,
        "provider": provider,
        "message": f"Disconnected {provider}" if success else f"{provider} was not connected",
    })


# ============================================================================
# PRIMITIVE RESOLVER ENDPOINTS (Phase 3 - Multi-Provider Support)
# ============================================================================

@app.get("/primitives")
async def list_primitives():
    """List all primitives and their available providers."""
    resolver = get_resolver()
    registry = get_registry()
    
    primitives = {}
    for primitive, connectors in registry.get_available_primitives().items():
        connected = resolver.get_available_providers(primitive, connected_only=True)
        preferred = resolver.get_preferred_provider(primitive)
        
        primitives[primitive] = {
            "connectors": connectors,
            "connected": connected,
            "preferred": preferred,
            "needs_selection": len(connected) > 1 and not preferred,
        }
    
    return JSONResponse({
        "primitives": primitives,
        "total": len(primitives),
    })


@app.get("/primitives/{primitive}/providers")
async def get_primitive_providers(primitive: str):
    """Get available providers for a specific primitive."""
    resolver = get_resolver()
    
    primitive = primitive.upper()
    needs_selection, providers = resolver.needs_provider_selection(primitive)
    connected = resolver.get_available_providers(primitive, connected_only=True)
    preferred = resolver.get_preferred_provider(primitive)
    
    return JSONResponse({
        "primitive": primitive,
        "providers": providers,
        "connected": connected,
        "preferred": preferred,
        "needs_selection": needs_selection,
    })


class PrimitiveExecuteRequest(BaseModel):
    """Request to execute a primitive operation."""
    operation: str
    params: dict = {}
    mode: str | None = None  # single, all, fallback, fastest
    connector: str | None = None  # Specific connector to use


@app.post("/primitives/{primitive}/execute")
async def execute_primitive(primitive: str, req: PrimitiveExecuteRequest):
    """
    Execute a primitive operation.
    
    This is the core execution endpoint that routes operations
    to the appropriate connector(s).
    
    Example:
        POST /primitives/EMAIL/execute
        {
            "operation": "search",
            "params": {"query": "invoice", "limit": 10},
            "mode": "all"  // Search all connected email providers
        }
    """
    resolver = get_resolver()
    
    primitive = primitive.upper()
    
    # Parse execution mode
    mode = None
    if req.mode:
        try:
            mode = ExecutionMode(req.mode)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid mode: {req.mode}. Use: single, all, fallback, fastest"
            )
    
    # Execute
    connectors = [req.connector] if req.connector else None
    
    result = await resolver.execute(
        primitive=primitive,
        operation=req.operation,
        params=req.params,
        mode=mode,
        connectors=connectors,
    )
    
    return JSONResponse(result.to_dict())


@app.get("/primitives/{primitive}/preview")
async def preview_primitive_execution(
    primitive: str, 
    operation: str,
    mode: str | None = None,
):
    """
    Preview how an operation would be executed.
    
    Shows which providers will be used before actually executing.
    """
    resolver = get_resolver()
    
    primitive = primitive.upper()
    exec_mode = None
    if mode:
        try:
            exec_mode = ExecutionMode(mode)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")
    
    preview = resolver.get_execution_preview(primitive, operation, exec_mode)
    
    return JSONResponse(preview)


class SetPreferredProviderRequest(BaseModel):
    """Request to set preferred provider for a primitive."""
    connector: str


@app.post("/primitives/{primitive}/preferred")
async def set_preferred_provider(primitive: str, req: SetPreferredProviderRequest):
    """Set the preferred provider for a primitive."""
    registry = get_registry()
    
    primitive = primitive.upper()
    success = registry.set_preferred_connector(primitive, req.connector)
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot set {req.connector} as preferred for {primitive}"
        )
    
    return JSONResponse({
        "success": True,
        "primitive": primitive,
        "preferred": req.connector,
    })


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
    
    # Check for OAuth credentials
    providers_configured = []
    providers_missing = []
    
    oauth_providers = [
        ("DISCORD", "DISCORD_CLIENT_ID"),
        ("MICROSOFT", "MICROSOFT_CLIENT_ID"),
        ("SLACK", "SLACK_CLIENT_ID"),
        ("GITHUB", "GITHUB_CLIENT_ID"),
        ("SPOTIFY", "SPOTIFY_CLIENT_ID"),
    ]
    
    for name, env_var in oauth_providers:
        if os.environ.get(env_var):
            providers_configured.append(name.lower())
        else:
            providers_missing.append(name.lower())
    
    if providers_configured:
        print(f"✅ OAuth configured: {', '.join(providers_configured)}")
    if providers_missing:
        print(f"⚠️  OAuth not configured: {', '.join(providers_missing)} (add to .env)")
    
    print("\n🌐 Opening http://localhost:8000 ...\n")
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
