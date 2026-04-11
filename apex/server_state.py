"""
Telic Server State - Shared state, factories, and helpers.

All global singletons and factory functions live here to avoid
circular imports between server.py and route modules.
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Load .env FIRST before any other imports that might use env vars
try:
    from dotenv import load_dotenv
    load_dotenv()  # apex/.env
    load_dotenv(Path(__file__).parent.parent / ".env")  # repo root .env
except ImportError:
    pass

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel

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
from intelligence import get_intelligence_hub, IntelligenceHub
from connectors.devtools import UnifiedDevTools

# Local Data Index & Sync Engine
from index import Index
from sync_engine import SyncEngine, ConnectorSyncAdapter, CalendarSyncAdapter, GmailSyncAdapter

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


# ============================================================
#  GLOBAL SINGLETONS
# ============================================================

# Telic engine (all primitives)
_telic_engine: Optional[TelicEngine] = None
_google_calendar: Optional["CalendarConnector"] = None
_gmail_connector: Optional["GmailConnector"] = None

# Local data index, background sync, and semantic search
_data_index: Optional[Index] = None
_sync_engine: Optional[SyncEngine] = None
_semantic_search = None  # SemanticSearch instance

# Track which Google services have authorized scopes
_google_connected_services: set = set()

# ReAct Agent state
_react_agent: Optional[ReActAgent] = None

# ---------------------------------------------------------------------------
# Per-user session state (multi-user safe)
# ---------------------------------------------------------------------------
import time as _time

_SESSION_TTL_SECONDS = 3600  # Evict sessions idle > 1 hour
_SESSION_LOCK = asyncio.Lock()


class UserSession:
    """Encapsulates per-conversation state for a single user session."""
    __slots__ = ("session_id", "messages", "agent", "react_state", "last_active")

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: list = []
        self.agent: Optional[ReActAgent] = None
        self.react_state: Optional[AgentState] = None
        self.last_active: float = _time.time()

    def touch(self) -> None:
        """Update last-active timestamp."""
        self.last_active = _time.time()

    def auto_save(self) -> None:
        """Persist session to SQLite."""
        if not self.messages:
            return
        title = "Untitled"
        for m in self.messages:
            if m["role"] == "user":
                title = m["content"][:80].strip()
                break
        session_store.save_session(self.session_id, title, self.messages)
        logger.info(f"Auto-saved session {self.session_id}: {title[:50]}")


_sessions: Dict[str, UserSession] = {}
_current_session_id: Optional[str] = None  # Default session for single-user compat


def _evict_stale_sessions() -> None:
    """Remove sessions idle longer than _SESSION_TTL_SECONDS.

    Call this while holding _SESSION_LOCK (or from a sync context
    where the caller already guarantees exclusivity).
    """
    now = _time.time()
    stale = [sid for sid, s in _sessions.items()
             if now - s.last_active > _SESSION_TTL_SECONDS and sid != _current_session_id]
    for sid in stale:
        session = _sessions.pop(sid)
        session.auto_save()
        logger.info(f"Evicted idle session {sid}")


def get_user_session(session_id: Optional[str] = None) -> UserSession:
    """Get or create a user session by ID.

    If *session_id* is ``None``, returns (or creates) the current default
    session — preserving single-user behaviour.
    """
    global _current_session_id

    if session_id is None:
        if _current_session_id and _current_session_id in _sessions:
            session = _sessions[_current_session_id]
            session.touch()
            return session
        session_id = session_store.new_session_id()

    if session_id not in _sessions:
        _evict_stale_sessions()
        _sessions[session_id] = UserSession(session_id=session_id)

    _current_session_id = session_id
    session = _sessions[session_id]
    session.touch()
    return session


def new_user_session() -> UserSession:
    """Save the current session and start a fresh one."""
    global _current_session_id

    # Auto-save current session
    if _current_session_id and _current_session_id in _sessions:
        _sessions[_current_session_id].auto_save()

    _evict_stale_sessions()

    session_id = session_store.new_session_id()
    session = UserSession(session_id=session_id)
    _sessions[session_id] = session
    _current_session_id = session_id
    return session

# Connector init tracking
_connectors_initialized = False

# OAuth pending states
_oauth_pending_states: Dict[str, Any] = {}

# Local file scanner
_file_scanner = None

# Credential store
_credential_store = None

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
        global _connectors_initialized
        _connectors_initialized = False
    
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
        
    model = "anthropic/claude-sonnet-4-20250514" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"
    
    # Auto-discover connectors from registry + credentials
    connectors = _build_connectors_from_registry()
    
    _telic_engine = TelicEngine(api_key=api_key, model=model, connectors=connectors)
    logger.info(f"Initialized with {len(connectors)} connectors: {list(connectors.keys())}")
    return _telic_engine


def _try_refresh_token(store, provider: str) -> bool:
    """Synchronously refresh an expired OAuth token using the refresh token."""
    try:
        import httpx
        from connectors.oauth_flow import OAUTH_PROVIDERS

        if provider not in OAUTH_PROVIDERS:
            return False

        cred = store.get(provider)
        if not cred or not cred.data.get("refresh_token"):
            return False

        client_creds = store.get_client_credentials(provider)
        if not client_creds:
            return False

        config = OAUTH_PROVIDERS[provider]
        resp = httpx.post(
            config.token_url,
            data={
                "client_id": client_creds["client_id"],
                "client_secret": client_creds.get("client_secret"),
                "refresh_token": cred.data["refresh_token"],
                "grant_type": "refresh_token",
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning(f"Token refresh failed for {provider}: {resp.status_code}")
            return False

        tokens = resp.json()
        store.save_token(
            provider=provider,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", cred.data.get("refresh_token")),
            expires_in=tokens.get("expires_in", 3600),
            scopes=cred.scopes,
            extra_data=cred.data.get("extra_data", {}),
        )
        logger.info(f"Refreshed expired token for {provider}")
        return True
    except Exception as e:
        logger.warning(f"Could not refresh {provider}: {e}")
        return False


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
    if _gmail_connector and _gmail_connector.connected:
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
        "telegram": "telegram",
        "hubspot": "hubspot",
        "stripe": "stripe",
    }
    
    # Check which providers have credentials (refresh expired ones)
    connected_providers = set()
    try:
        for provider in store.list_providers():
            if store.has_valid(provider):
                connected_providers.add(provider)
            elif store.has(provider) and store.needs_refresh(provider):
                # Token expired but refresh token may still be valid — try refresh
                if _try_refresh_token(store, provider):
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
        "telegram": "TELEGRAM_BOT_TOKEN",
        "hubspot": "HUBSPOT_ACCESS_TOKEN",
        "stripe": "STRIPE_SECRET_KEY",
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
    # Map connector init parameter names for token injection from credential store
    _token_param_names = {
        "spotify": "access_token",
        "discord": "bot_token",
        "slack": "token",
        "github": "token",
        "todoist": "api_token",
        "telegram": "bot_token",
        "notion": "api_key",
        "linear": "api_key",
        "trello": "api_key",
        "hubspot": "access_token",
        "stripe": "api_key",
        "dropbox": "access_token",
        "weather": "api_key",
        "news": "api_key",
        "airtable": "api_key",
        "linkedin": "access_token",
        "smartthings": "access_token",
    }
    
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
            # Try to inject token from credential store
            # Microsoft connectors get tokens via GraphClient, not constructor args
            kwargs = {}
            if metadata.provider != "microsoft":
                token = store.get_token(metadata.provider)
                if token and metadata.provider in _token_param_names:
                    param_name = _token_param_names[metadata.provider]
                    kwargs[param_name] = token
            
            instance = metadata.connector_class(**kwargs)
            connectors[engine_key] = instance
            logger.info(f"Auto-wired: {metadata.display_name} -> {engine_key}")
        except Exception as e:
            logger.warning(f"Failed to instantiate {metadata.name}: {e}")
    
    return connectors


async def _connect_engine_connectors(engine: TelicEngine):
    """Connect all connectors that have an async connect() method.
    
    Called once after engine init from an async context.
    Connectors that are already connected or fail to connect are skipped.
    """
    to_remove = []
    for key, connector in list(engine._connectors.items()):
        if hasattr(connector, 'connect'):
            # Check if already connected (supports .connected property/attr or .is_connected() method)
            is_connected = False
            if hasattr(connector, 'connected'):
                val = getattr(connector, 'connected')
                is_connected = val() if callable(val) else val
            elif hasattr(connector, 'is_connected'):
                val = getattr(connector, 'is_connected')
                is_connected = val() if callable(val) else val
            
            if not is_connected:
                try:
                    result = await connector.connect()
                    connected_now = False
                    if isinstance(result, bool):
                        connected_now = result
                    elif hasattr(connector, 'connected'):
                        val = getattr(connector, 'connected')
                        connected_now = val() if callable(val) else bool(val)
                    elif hasattr(connector, 'is_connected'):
                        val = getattr(connector, 'is_connected')
                        connected_now = val() if callable(val) else bool(val)

                    if connected_now:
                        logger.info(f"Connected: {key}")
                    else:
                        logger.warning(f"Connect failed for {key}: connector returned not connected")
                        to_remove.append(key)
                except Exception as e:
                    logger.warning(f"Connect failed for {key}: {e}")
                    to_remove.append(key)

    # Remove connectors that failed to connect so they do not surface as usable tools.
    for key in to_remove:
        engine._connectors.pop(key, None)


_connectors_initialized = False

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
    logger.info(f"Loaded {len(tools)} tools from {len(engine._primitives)} primitives")
    
    # Create LLM client
    from llm_factory import create_anthropic_client, create_openai_client
    llm_client, llm_mode = create_anthropic_client()
    if not llm_client:
        llm_client, llm_mode = create_openai_client()
    if not llm_client:
        return None
    logger.info(f"LLM mode: {llm_mode}")
    
    # Share LLM client with the intent router for AI-based classification
    from intent_router import set_llm_client
    set_llm_client(llm_client)
    
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
- For AMBIGUOUS targets (which contact? which account? which files?): ask. Don't guess identity or scope.
- For IRREVERSIBLE actions (sending emails, creating events, payments): confirm details before executing.
- For CREATIVE tasks (documents, presentations, charts): just start with reasonable defaults. The user can iterate.
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
_devtools: Optional[UnifiedDevTools] = None


def get_proactive_monitor() -> ProactiveMonitor:
    """Get or create the ProactiveMonitor singleton."""
    global _proactive_monitor
    if _proactive_monitor is None:
        _proactive_monitor = ProactiveMonitor()
    return _proactive_monitor


def get_cross_service_intel() -> CrossServiceIntelligence:
    """Get CrossServiceIntelligence via the IntelligenceHub (shared instance)."""
    hub = get_intelligence_hub()
    return hub._intel


def get_devtools() -> UnifiedDevTools:
    """Get or create the UnifiedDevTools singleton."""
    global _devtools
    if _devtools is None:
        _devtools = UnifiedDevTools()
    return _devtools


async def startup_event(app=None):
    """Try to reconnect Google services if tokens exist from previous session."""
    global _google_calendar, _gmail_connector, _google_connected_services
    
    if not HAS_GOOGLE_CALENDAR:
        logger.info("Google API libraries not available")
        return
    
    try:
        auth = get_google_auth()
        
        # Check if we have existing tokens (no OAuth prompt)
        if auth._token_file.exists():
            logger.info("Found existing Google tokens, attempting reconnect...")
            
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
                    'youtube': 'youtube',
                }
                
                # Populate connected services based on token scopes
                _google_connected_services.clear()
                for scope in token_scopes:
                    for key, service in scope_to_service.items():
                        if key in scope.lower():
                            _google_connected_services.add(service)
                
                has_calendar = 'calendar' in _google_connected_services
                has_gmail = 'gmail' in _google_connected_services
                
                logger.info(f"Token scopes: {_google_connected_services}")
                
                # Connect Calendar
                if has_calendar:
                    _google_calendar = CalendarConnector(auth)
                    if await _google_calendar.connect():
                        logger.info("Google Calendar reconnected!")
                    else:
                        logger.warning("Google Calendar reconnect failed (insufficient scope or auth)")
                        _google_calendar = None
                
                # Connect Gmail
                if has_gmail:
                    try:
                        from connectors.gmail import GmailConnector
                        _gmail_connector = GmailConnector(auth)
                        if await _gmail_connector.connect():
                            logger.info("Gmail reconnected!")
                        else:
                            logger.warning("Gmail connection failed")
                            _gmail_connector = None
                    except Exception as gmail_err:
                        logger.warning(f"Gmail reconnect failed: {gmail_err}")
                        _gmail_connector = None
                else:
                    logger.info("Gmail scopes not in token - user needs to re-authenticate with Gmail access")
            else:
                logger.warning("Google tokens expired or invalid")
                
            # Rebuild engine with connectors
            get_telic_engine(force_rebuild=True)
        else:
            logger.info("No Google tokens found - user needs to connect")
            
    except Exception as e:
        logger.warning(f"Google reconnect failed: {e}")

    # Reconnect Microsoft services if MSAL token cache or credential store has tokens
    try:
        from connectors.microsoft_auth import get_microsoft_auth
        ms_auth = get_microsoft_auth()
        ms_reconnected = False
        
        # Try MSAL token cache first
        if ms_auth.has_credentials() and ms_auth._token_cache_file.exists():
            logger.info("Found Microsoft token cache, attempting reconnect...")
            from connectors.microsoft_graph import GraphClient
            ms_client = GraphClient(auth=ms_auth)
            if await ms_client.connect():
                logger.info("Microsoft Graph reconnected via MSAL!")
                ms_reconnected = True
        
        # Fall back to credential store (web OAuth flow stores tokens there)
        if not ms_reconnected:
            store = get_cred_store()
            if store.has("microsoft"):
                if store.needs_refresh("microsoft"):
                    _try_refresh_token(store, "microsoft")
                if store.has_valid("microsoft"):
                    logger.info("Microsoft reconnected via credential store")
                    ms_reconnected = True
        
        if ms_reconnected:
            get_telic_engine(force_rebuild=True)
        elif ms_auth.has_credentials() or get_cred_store().has("microsoft"):
            logger.warning("Microsoft token cache expired - user needs to re-authenticate")
    except Exception as e:
        logger.warning(f"Microsoft reconnect failed (non-fatal): {e}")

    # Reconnect Spotify if credentials exist in store
    try:
        store = get_cred_store()
        if store.has("spotify") and store.needs_refresh("spotify"):
            _try_refresh_token(store, "spotify")
        spotify_token = store.get_token("spotify")
        if spotify_token or os.environ.get("SPOTIFY_CLIENT_ID"):
            logger.info("Found Spotify credentials, will reconnect on engine build")
            # Spotify connector is auto-wired by _build_connectors_from_registry
            if not _telic_engine:
                get_telic_engine(force_rebuild=True)
    except Exception as e:
        logger.warning(f"Spotify reconnect check failed (non-fatal): {e}")

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
        logger.info(f"ProactiveMonitor started with services: {list(monitor._service_adapters.keys())}")
    except Exception as e:
        logger.warning(f"ProactiveMonitor start failed (non-fatal): {e}")

    # Initialize IntelligenceHub and wire to connected services
    try:
        hub = get_intelligence_hub()
        stats = hub.get_stats()
        mem_facts = stats.get("memory", {}).get("total_facts", 0)
        pref_count = stats.get("preferences", {}).get("learned_preferences", 0)
        pat_count = stats.get("patterns", {}).get("detected_patterns", 0)
        logger.info(f"IntelligenceHub ready: {mem_facts} facts, {pref_count} preferences, {pat_count} patterns")
    except Exception as e:
        logger.warning(f"IntelligenceHub init failed (non-fatal): {e}")

    # Start local data index + background sync engine
    global _data_index, _sync_engine
    try:
        _data_index = Index()  # Opens/creates apex/sqlite/index.db
        _sync_engine = SyncEngine(_data_index)

        # Make the index available to primitives
        from apex_engine import set_data_index
        set_data_index(_data_index)

        # Auto-register sync adapters for all connected services
        engine = get_telic_engine()
        if engine:
            # Calendar gets a specialized adapter with syncToken support
            cal_connector = engine._connectors.get("calendar")
            cal_connected = False
            if cal_connector and hasattr(cal_connector, 'connected'):
                val = getattr(cal_connector, 'connected')
                cal_connected = val() if callable(val) else bool(val)
            elif cal_connector and hasattr(cal_connector, 'is_connected'):
                val = getattr(cal_connector, 'is_connected')
                cal_connected = val() if callable(val) else bool(val)
            if cal_connector and cal_connected and hasattr(cal_connector, 'sync_events'):
                _sync_engine.register(CalendarSyncAdapter(
                    connector=cal_connector,
                    default_interval=300,
                ))

            # All other connectors use the generic adapter
            _sync_recipes = {
                ("gmail", "gmail"):                ("list_messages",  {"max_results": 100}, 300),
                ("contacts", "google_contacts"):   ("list_contacts",  {"max_results": 500}, 900),
                ("drive", "google_drive"):         ("list_files",     {"max_results": 100}, 600),
                ("todoist", "todoist"):             ("list_tasks",     {}, 300),
                ("microsoft_todo", "microsoft_todo"): ("list_tasks",  {}, 300),
                ("outlook", "outlook"):            ("list_messages",  {"max_results": 100}, 300),
                ("outlook_calendar", "outlook_calendar"): ("list_events", {"max_results": 250}, 300),
                ("onedrive", "onedrive"):          ("list_files",     {"max_results": 100}, 600),
                ("contacts_microsoft", "microsoft_contacts"): ("list_contacts", {"max_results": 500}, 900),
                ("slack", "slack"):                ("list_messages",  {"max_results": 50}, 300),
                ("github", "github"):              ("list_notifications", {"per_page": 50}, 600),
                ("notion", "notion"):              ("list_pages",     {"max_results": 100}, 600),
                ("trello", "trello"):              ("list_cards",     {}, 600),
                ("linear", "linear"):              ("list_issues",    {}, 600),
                ("jira", "jira"):                  ("list_issues",    {}, 600),
                ("dropbox", "dropbox"):            ("list_files",     {"limit": 100}, 600),
                ("hubspot", "hubspot"):            ("list_contacts",  {"limit": 100}, 900),
                ("zoom", "zoom"):                  ("list_meetings",  {"page_size": 100}, 600),
            }

            for (engine_key, index_source), (method, kwargs, interval) in _sync_recipes.items():
                connector = engine._connectors.get(engine_key)
                if connector and hasattr(connector, method):
                    # Only register if actually connected — don't sync dead services
                    is_conn = False
                    if hasattr(connector, 'connected'):
                        val = getattr(connector, 'connected')
                        is_conn = val() if callable(val) else val
                    elif hasattr(connector, 'is_connected'):
                        val = getattr(connector, 'is_connected')
                        is_conn = val() if callable(val) else val
                    else:
                        is_conn = True  # No check available, assume connected

                    if is_conn:
                        _sync_engine.register(ConnectorSyncAdapter(
                            source=index_source,
                            connector=connector,
                            fetch_method=method,
                            fetch_kwargs=kwargs,
                            default_interval=interval,
                        ))
                    else:
                        logger.debug(f"Skipping sync for {engine_key}: not connected")

        # Also register globals that might not be in engine._connectors yet
        if _google_calendar and _google_calendar.connected and "google_calendar" not in _sync_engine._adapters:
            _sync_engine.register(CalendarSyncAdapter(
                connector=_google_calendar,
                default_interval=300,
            ))
        if _gmail_connector and _gmail_connector.connected and "gmail" not in _sync_engine._adapters:
            _sync_engine.register(GmailSyncAdapter(
                connector=_gmail_connector,
                default_interval=300,
            ))

        # Start background sync loop
        await _sync_engine.start()
        logger.info(f"Data index + sync engine started ({len(_sync_engine._adapters)} sources)")
    except Exception as e:
        logger.warning(f"Data index/sync failed (non-fatal): {e}")

    # Initialize semantic search (vector embeddings)
    global _semantic_search
    if _data_index is None:
        logger.info("Skipping semantic search (data index not available)")
    else:
        try:
            from semantic_search import SemanticSearch
            _semantic_search = SemanticSearch(_data_index)
            if await _semantic_search.initialize():
                # Wire into sync engine so new data gets embedded automatically
                if _sync_engine:
                    _sync_engine.set_semantic_search(_semantic_search)
                # Wire into search primitive for agent tool access
                try:
                    from apex_engine import set_semantic_search as set_ss
                    set_ss(_semantic_search)
                except Exception:
                    pass
                # Embed any existing un-embedded objects in background
                asyncio.create_task(_semantic_search.embed_all())
                ss_stats = _semantic_search.stats
                if ss_stats.get("backend") in {"hash", "charhash"}:
                    logger.warning(
                        "Semantic search running in fallback mode (%s): results are available but lower quality",
                        ss_stats.get("backend"),
                    )
                logger.info(f"Semantic search ready: {ss_stats}")
            else:
                logger.info("Semantic search: no embedding backend available (non-fatal)")
                _semantic_search = None
        except Exception as e:
            logger.warning(f"Semantic search init failed (non-fatal): {e}")
            _semantic_search = None

    # Initialize webhooks + smart prefetch
    try:
        from webhooks import get_webhook_manager
        _webhook_manager = get_webhook_manager(_sync_engine)
        if _webhook_manager:
            if app:
                _webhook_manager.register_routes(app)
            # Setup webhook subscriptions (only works with WEBHOOK_BASE_URL)
            webhook_result = await _webhook_manager.setup_all(
                calendar_connector=_google_calendar,
                gmail_connector=_gmail_connector,
            )
            # Always start smart prefetch (works without public URL)
            await _webhook_manager.start_prefetch()
            logger.info(f"Webhooks: {webhook_result}")
            logger.info("Smart prefetch started")
    except Exception as e:
        logger.warning(f"Webhooks/prefetch init failed (non-fatal): {e}")

    # Auto-start local file scanner if user previously opted in
    global _file_scanner
    try:
        if _data_index:
            from local_files import load_settings, LocalFileScanner
            file_settings = load_settings(_data_index)
            if file_settings.enabled:
                _file_scanner = LocalFileScanner(
                    index=_data_index,
                    settings=file_settings,
                    semantic_search=_semantic_search,
                )
                started = await _file_scanner.start()
                if started:
                    logger.info(f"Local file scanner started ({len(file_settings.scan_directories)} dirs)")
                else:
                    logger.warning("Local file scanner enabled but failed to start")
            else:
                logger.info("Local file scanner: not enabled (opt-in via POST /files/settings)")
    except Exception as e:
        logger.warning(f"Local file scanner init failed (non-fatal): {e}")

    # Start routine scheduler
    try:
        from routines import get_routine_runner
        _routine_runner = get_routine_runner()
        await _routine_runner.start()
        from routines import get_routine_store
        count = len([r for r in get_routine_store().list() if r["enabled"]])
        logger.info(f"Routine scheduler started ({count} active routines)")
    except Exception as e:
        logger.warning(f"Routine scheduler init failed (non-fatal): {e}")

    # Start nudge engine (AI-powered proactive suggestions)
    try:
        from nudge_engine import get_nudge_engine
        _nudge_engine = get_nudge_engine()
        await _nudge_engine.start()
        logger.info("NudgeEngine started")
    except Exception as e:
        logger.warning(f"NudgeEngine init failed (non-fatal): {e}")



def get_cred_store():
    """Get singleton credential store."""
    global _credential_store
    if _credential_store is None:
        _credential_store = get_credential_store()
    return _credential_store




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




class ReactRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    orchestration_mode: Optional[str] = None


class ReactApproveRequest(BaseModel):
    approved: bool
    session_id: Optional[str] = None
    updated_params: Optional[Dict[str, Any]] = None
    orchestration_mode: Optional[str] = None



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


def _friendly_tool_name(tool_name: str) -> str:
    return (tool_name or "action").replace("_", " ").strip().title()


def _approval_summary(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Build a compact, human-readable approval summary for side-effect actions."""
    p = params or {}
    highlights = []
    action = _friendly_tool_name(tool_name)

    def _add(label: str, value: Any, max_len: int = 180) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        if len(text) > max_len:
            text = text[:max_len] + "..."
        highlights.append({"label": label, "value": text})

    t = (tool_name or "").lower()

    if "email" in t and any(k in t for k in ("send", "draft", "reply", "forward")):
        action = "Send Email" if "send" in t else _friendly_tool_name(tool_name)
        _add("To", p.get("to") or p.get("recipient"))
        _add("Cc", p.get("cc"))
        _add("Subject", p.get("subject"))
        attachments = p.get("attachments")
        if isinstance(attachments, list) and attachments:
            _add("Attachments", ", ".join(str(a) for a in attachments[:4]))
    elif "document" in t and "create" in t:
        action = "Create Document"
        path_val = p.get("path") or p.get("folder") or p.get("directory")
        name_val = p.get("name") or p.get("filename") or p.get("title")
        if not name_val and isinstance(path_val, str) and path_val.strip():
            # Derive filename from path-like values for clearer approval context.
            parts = path_val.replace("\\", "/").split("/")
            name_val = parts[-1] if parts else None
        _add("Name", name_val)
        _add("Path", path_val)
        _add("Format", p.get("format") or p.get("type"))
        _add("Content", p.get("content"), max_len=240)
        data_val = p.get("data")
        if isinstance(data_val, list):
            _add("Rows", len(data_val))
            if data_val and isinstance(data_val[0], dict):
                sample_keys = list(data_val[0].keys())[:4]
                if sample_keys:
                    _add("Columns", ", ".join(sample_keys))
    elif "calendar" in t and any(k in t for k in ("create", "add", "schedule")):
        action = "Create Calendar Event"
        _add("Title", p.get("title") or p.get("summary"))
        _add("Start", p.get("start") or p.get("start_time"))
        _add("End", p.get("end") or p.get("end_time"))
        _add("Attendees", p.get("attendees"))
    else:
        for key in ("name", "title", "to", "subject", "path", "message", "content"):
            if key in p:
                _add(key.title(), p.get(key), max_len=200)
        if not highlights:
            for idx, (k, v) in enumerate((p or {}).items()):
                if idx >= 4:
                    break
                _add(k.replace("_", " ").title(), v, max_len=120)

    return {
        "action": action,
        "tool": tool_name,
        "highlights": highlights,
    }


def step_to_dict(step: Step) -> Dict[str, Any]:
    """Convert a Step to a JSON-serializable dict."""
    return {
        "tool": step.tool_call.name,
        "params": step.tool_call.params,
        "status": step.status.value,
        "result": serialize_result(step.result),
        "error": step.error,
        "requires_approval": step.requires_approval,
        "approval_summary": _approval_summary(step.tool_call.name, step.tool_call.params) if step.requires_approval else None,
    }


def step_to_sse_dict(step: Step) -> Dict[str, Any]:
    """Convert a Step to a lightweight dict for SSE streaming (no full results)."""
    result_data = serialize_result(step.result)
    # For SSE mid-stream events, send only a compact preview
    if result_data is not None:
        try:
            result_json = json.dumps(result_data) if not isinstance(result_data, str) else result_data
        except (TypeError, ValueError):
            result_json = str(result_data)
        if len(result_json) > 1500:
            result_data = f"[{len(result_json)} bytes — see final results]"
    params = step.tool_call.params or {}
    compact_params = params
    if step.status != StepStatus.PENDING_APPROVAL:
        compact_params = {k: (v if len(str(v)) < 100 else str(v)[:100] + "...") for k, v in params.items()}
    return {
        "tool": step.tool_call.name,
        "params": compact_params,
        "status": step.status.value,
        "result": result_data,
        "error": step.error,
        "requires_approval": step.requires_approval,
        "approval_summary": _approval_summary(step.tool_call.name, params) if step.requires_approval else None,
    }


def state_to_response(state: AgentState) -> Dict[str, Any]:
    """Convert AgentState to API response."""
    resp = {
        "steps": [step_to_dict(s) for s in state.steps],
        "pending_approval": step_to_dict(state.pending_approval) if state.pending_approval else None,
        "is_complete": state.is_complete,
        "response": state.final_response,
    }
    if state.llm_calls > 0:
        resp["usage"] = {
            "input_tokens": state.input_tokens,
            "output_tokens": state.output_tokens,
            "cache_read_tokens": state.cache_read_tokens,
            "cache_creation_tokens": state.cache_creation_tokens,
            "llm_calls": state.llm_calls,
            "estimated_cost_usd": round(state.estimated_cost_usd, 6),
        }
    return resp


async def select_primitives_for_request(message: str, all_primitives: dict) -> dict:
    """
    DEPRECATED: Dynamic primitive selection caused conversation context issues.
    Now we use all primitives and let the LLM choose which to use.
    Keeping this function for potential future use with smarter filtering.
    """
    return all_primitives



async def get_session_agent(session: Optional[UserSession] = None, force_new: bool = False) -> Optional[ReActAgent]:
    """
    Get or create a session-persistent ReAct agent.
    
    Unlike the old approach that created fresh agents per request,
    this maintains conversation context like ChatGPT/Gemini.
    If *session* is provided, the agent is scoped to that session.
    """
    if session is None:
        session = get_user_session()

    if force_new:
        session.agent = None
        session.messages = []
    
    if session.agent is not None:
        return session.agent
    
    # Need API key or proxy
    from llm_factory import get_llm_mode
    if get_llm_mode() == "none":
        return None
    
    # Get the Telic engine
    engine = get_telic_engine()
    if not engine:
        return None
    
    # Connect any connectors that need async initialization
    global _connectors_initialized
    if not _connectors_initialized:
        await _connect_engine_connectors(engine)
        _connectors_initialized = True
    
    # Use ALL primitives - let the LLM decide what's relevant
    tools = primitives_to_tools(engine._primitives)
    logger.info(f"Created agent with {len(tools)} tools")
    
    # Create LLM client
    from llm_factory import create_anthropic_client, create_openai_client
    llm_client, llm_mode = create_anthropic_client()
    if not llm_client:
        llm_client, llm_mode = create_openai_client()
    if not llm_client:
        return None
    
    from datetime import datetime, timedelta
    now = datetime.now()
    # Build date context with upcoming days for accurate scheduling
    date_context = f"""TODAY: {now.strftime("%A, %B %d, %Y")} ({now.strftime("%Y-%m-%d")})
This week:
"""
    for i in range(7):
        d = now + timedelta(days=i)
        date_context += f"  {d.strftime('%A %b %d')}: {d.strftime('%Y-%m-%d')}\n"
    
    # Gather intelligence context for system prompt
    intel_section = ""
    try:
        hub = get_intelligence_hub()
        parts = []
        
        # Get learned preferences
        prefs = await hub.get_preferences()
        if prefs:
            pref_items = list(prefs.values())[:8] if isinstance(prefs, dict) else list(prefs)[:8]
            pref_lines = [f"- {p.key}: {p.value} (confidence: {p.confidence:.0%})" for p in pref_items]
            parts.append("LEARNED USER PREFERENCES:\n" + "\n".join(pref_lines))
        
        # Get detected patterns
        patterns = await hub.get_patterns(min_confidence=0.5)
        if patterns:
            pat_lines = [f"- {p.name}: {p.description}" for p in patterns[:5]]
            parts.append("DETECTED PATTERNS:\n" + "\n".join(pat_lines))
        
        # Get memory stats
        stats = hub._memory.get_stats()
        if stats.get("total_facts", 0) > 0:
            parts.append(f"MEMORY: {stats['total_facts']} facts remembered about {stats.get('total_entities', 0)} entities")
        
        if parts:
            intel_section = "\n\n" + "\n\n".join(parts) + "\n"
    except Exception as e:
        logger.warning(f"System prompt enrichment failed (non-fatal): {e}")
    
    system_prompt = f"""You are Ziggy, an AI assistant that helps users get things done.

{date_context}

You have access to the user's email, calendar, files, tasks, and other services.
Use tools to accomplish what the user asks. You can call multiple tools in parallel when the calls are independent.

Be efficient — don't repeat searches with slight variations. If a search returns no results, broaden the query or try a different approach rather than retrying similar queries.
{intel_section}
CONVERSATION CONTEXT:
- You have full memory of this conversation session
- References like "the first one", "send it", "the information above" refer to earlier in THIS conversation
- If user mentions something from earlier, use that context

IMPORTANT BEHAVIORS:
- When you find multiple matches, ask user which one they want
- For AMBIGUOUS targets (which contact? which account? which files?): ask. Don't guess identity or scope.
- For IRREVERSIBLE actions (sending emails, creating events, payments): confirm details before executing.
- For CREATIVE tasks (documents, presentations, charts): just start with reasonable defaults. The user can iterate.
- Trust your tool results. If a tool returns data, present it. Do not retry with different parameters or search for confirmation.
- LEARN: When you discover something useful about the user — their preferences, important people, which services/calendars/playlists they care about, how they like things done — use KNOWLEDGE.remember to store it. You have a persistent memory. Use it so you get better over time.

When complete, summarize what was done."""
    
    session.agent = ReActAgent(
        llm_client=llm_client,
        tools=tools,
        system_prompt=system_prompt,
    )
    
    return session.agent


def _auto_save_session(session: Optional["UserSession"] = None) -> None:
    """Save a session to SQLite. Delegates to UserSession.auto_save()."""
    if session is None:
        session = get_user_session() if _current_session_id else None
    if session:
        session.auto_save()



class ApproveActionRequest(BaseModel):
    action_id: str
    modifications: Optional[Dict[str, Any]] = None
    remember_pattern: bool = False
    pattern_context: Optional[Dict[str, Any]] = None


class UndoActionRequest(BaseModel):
    action_id: str

class ApiKeyRequest(BaseModel):
    """Request to set an API key."""
    provider: str  # "anthropic" or "openai"
    api_key: str


class SaveCredentialRequest(BaseModel):
    """Request to save a credential."""
    provider: str
    credential_type: str = "api_key"
    api_key: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class SetPreferenceRequest(BaseModel):
    primitive: str
    connector: str



class OAuthInitRequest(BaseModel):
    """Request to start OAuth flow."""
    client_id: str
    client_secret: str | None = None
    services: list[str] | None = None  # e.g., ["gmail", "calendar"] for Google
    scopes: list[str] | None = None    # Custom scopes
    redirect_uri: str | None = None



class PrimitiveExecuteRequest(BaseModel):
    """Request to execute a primitive operation."""
    operation: str
    params: dict = {}
    mode: str | None = None  # single, all, fallback, fastest
    connector: str | None = None  # Specific connector to use



class SetPreferredProviderRequest(BaseModel):
    """Request to set preferred provider for a primitive."""
    connector: str


