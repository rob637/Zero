"""
Telic Web Server - AI Operating System

Run with:
    cd apex
    python server.py

Then open http://localhost:8000 in your browser.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Shared state and helpers
import server_state as state
from server_state import (
    get_telic_engine, get_proactive_monitor, get_devtools,
    get_cred_store, startup_event,
    _data_index, _sync_engine, _semantic_search,
    _google_calendar, _gmail_connector, _google_connected_services,
    HAS_GOOGLE_CALENDAR,
    create_client_from_env,
    get_credential_store, get_resolver,
    ConnectorRegistry,
)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Route modules
from routes.oauth import router as oauth_router
from routes.react import router as react_router
from routes.intelligence import router as intelligence_router
from routes.routines import router as routines_router
from routes.nudges import router as nudges_router


@asynccontextmanager
async def _lifespan(app):
    await startup_event(app)
    yield


# Initialize
app = FastAPI(title="Telic", description="AI Operating System", lifespan=_lifespan)

# CORS - restrict to known origins
_cors_origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "tauri://localhost",
    "https://tauri.localhost",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# Rate limiting — simple in-memory token bucket per IP
import time as _time
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse

class _RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiter. 30 req/min for chat, 120 req/min for everything else."""
    def __init__(self, app):
        super().__init__(app)
        self._buckets: Dict[str, list] = defaultdict(lambda: [0.0, 0])  # [last_refill, tokens]
        self._chat_paths = {"/react/chat", "/react/chat/stream"}

    async def dispatch(self, request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path
        is_chat = any(path.startswith(p) for p in self._chat_paths)
        limit = 30 if is_chat else 120
        key = f"{client_ip}:{'chat' if is_chat else 'api'}"

        bucket = self._buckets[key]
        now = _time.time()
        elapsed = now - bucket[0]
        bucket[0] = now
        bucket[1] = min(limit, bucket[1] + elapsed * (limit / 60.0))
        if bucket[1] < 1:
            return StarletteJSONResponse(
                {"error": "Rate limit exceeded. Try again shortly."},
                status_code=429,
                headers={"Retry-After": "5"},
            )
        bucket[1] -= 1
        return await call_next(request)

app.add_middleware(_RateLimitMiddleware)

# Include route modules
app.include_router(oauth_router)
app.include_router(react_router)
app.include_router(intelligence_router)
app.include_router(routines_router)
app.include_router(nudges_router)



@app.get("/")
async def root():
    """Serve the UI with no-cache headers so updates are always picked up."""
    return FileResponse(
        Path(__file__).parent / "ui" / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

@app.get("/sync/status")
async def get_sync_status():
    """Get sync engine status: per-source sync state and index stats."""
    if not state._sync_engine:
        return JSONResponse({"running": False, "error": "Sync engine not initialized"})
    return JSONResponse(state._sync_engine.status)


@app.post("/sync/now")
async def trigger_sync(source: Optional[str] = None):
    """Force immediate sync. Optionally specify a single source."""
    if not state._sync_engine:
        raise HTTPException(400, "Sync engine not initialized")
    result = await state._sync_engine.sync_now(source=source)
    return JSONResponse(result)


@app.get("/health")
async def health_check():
    """System health: index integrity, sync status, embedding coverage."""
    report = {"status": "healthy", "components": {}}

    # Index health
    if state._data_index:
        idx_health = state._data_index.health()
        report["components"]["index"] = idx_health
        if idx_health["status"] != "healthy":
            report["status"] = idx_health["status"]
    else:
        report["components"]["index"] = {"status": "unavailable"}
        report["status"] = "degraded"

    # Sync engine
    if state._sync_engine:
        report["components"]["sync"] = {
            "status": "running" if state._sync_engine._running else "stopped",
            "adapters": len(state._sync_engine._adapters),
        }
    else:
        report["components"]["sync"] = {"status": "unavailable"}

    # Semantic search
    if state._semantic_search and state._semantic_search.ready:
        ss_stats = state._semantic_search.stats
        report["components"]["semantic_search"] = {
            "status": "ready",
            "vectors": ss_stats.get("total_vectors", 0),
            "backend": ss_stats.get("backend", "unknown"),
        }
    else:
        report["components"]["semantic_search"] = {"status": "unavailable"}

    # Connected services
    try:
        credential_store = state.get_credential_store()
        providers = credential_store.list_providers()
    except Exception:
        providers = []
    try:
        devtools = state.get_devtools()
        devtools_providers = devtools.providers if hasattr(devtools, 'providers') else {}
    except Exception:
        devtools_providers = {}
    try:
        monitor = state.get_proactive_monitor()
        monitor_services = list(monitor._services.keys()) if hasattr(monitor, '_services') else []
    except Exception:
        monitor_services = []
    report["llm_configured"] = state.create_client_from_env() is not None
    report["connected_services"] = len(providers)
    report["services"] = {
        "google": "google" in providers,
        "microsoft": "microsoft" in providers,
        "github": "github" in devtools_providers,
        "jira": "jira" in devtools_providers,
        "slack": "slack" in monitor_services,
    }

    return JSONResponse(report)


@app.post("/index/vacuum")
async def index_vacuum():
    """Run VACUUM on the index database to reclaim space."""
    if not state._data_index:
        raise HTTPException(400, "Index not available")
    result = state._data_index.vacuum()
    return JSONResponse(result)


@app.post("/index/rebuild-fts")
async def index_rebuild_fts():
    """Rebuild the FTS5 full-text search index."""
    if not state._data_index:
        raise HTTPException(400, "Index not available")
    result = state._data_index.rebuild_fts()
    return JSONResponse(result)


@app.get("/discovery/apps")
async def discover_apps():
    """Scan local system for installed apps and suggest connectors.
    
    Returns ALL available connectors with 'detected' flag for ones
    found locally. Apps not found are still listed — users may use
    web versions.
    """
    from app_discovery import get_all_available_connectors, scan_apps
    result = scan_apps()
    connectors = get_all_available_connectors()
    return JSONResponse({
        "platform": result.platform,
        "scan_time_ms": round(result.scan_time_ms, 1),
        "apps_found": len(result.apps),
        "detected_apps": [
            {"name": a.name, "id": a.app_id, "source": a.source}
            for a in result.apps
            if a.app_id in {s.connector_name for s in result.suggestions}
               or a.app_id in _APP_TO_CONNECTOR_IDS
        ],
        "suggestions": [
            {"connector": s.connector_name, "display": s.display_name,
             "reason": s.reason, "priority": s.priority}
            for s in result.suggestions
        ],
        "all_connectors": connectors,
    })


# Pre-compute set for the endpoint above
from app_discovery import _APP_TO_CONNECTOR as _APP_TO_CONNECTOR_MAP
_APP_TO_CONNECTOR_IDS = set(_APP_TO_CONNECTOR_MAP.keys())


@app.get("/search/semantic")
async def semantic_search_endpoint(
    q: str,
    kind: Optional[str] = None,
    limit: int = 20,
):
    """Cross-service semantic search.

    Finds things like "that budget spreadsheet John sent last week"
    across email, calendar, drive, tasks, etc.
    """
    if not state._semantic_search or not state._semantic_search.ready:
        raise HTTPException(503, "Semantic search not available")
    results = await state._semantic_search.search(q, kind=kind, limit=limit)
    return JSONResponse({
        "query": q,
        "count": len(results),
        "results": [
            {
                "id": obj.id,
                "kind": obj.kind.value,
                "source": obj.source,
                "title": obj.title,
                "body": (obj.body[:300] + "...") if obj.body and len(obj.body) > 300 else obj.body,
                "timestamp": obj.timestamp.isoformat() if obj.timestamp else None,
                "participants": obj.participants,
                "score": round(score, 3),
            }
            for obj, score in results
        ],
    })


@app.get("/search/stats")
async def search_stats():
    """Get semantic search stats (embedded count, backend, etc.)."""
    if not state._semantic_search:
        return JSONResponse({"ready": False})
    return JSONResponse(state._semantic_search.stats)


# ==========================================================
# Local File Indexer — opt-in PC file scanning
# ==========================================================

_file_scanner = None  # Optional[LocalFileScanner]



@app.get("/files/settings")
async def get_file_index_settings():
    """Get current local file indexing settings."""
    from local_files import load_settings, FileIndexSettings
    if not state._data_index:
        return JSONResponse({"enabled": False, "error": "Index not available"})
    settings = load_settings(state._data_index)
    return JSONResponse({
        "settings": settings.to_dict(),
        "default_directories": FileIndexSettings.default_directories(),
        "scanner_status": state._file_scanner.status if state._file_scanner else {"enabled": False, "running": False},
    })


@app.post("/files/settings")
async def update_file_index_settings(request: Request):
    """Update local file indexing settings. User opts in/out here."""
    # _file_scanner in state module
    from local_files import (
        FileIndexSettings, LocalFileScanner, load_settings, save_settings,
    )
    if not state._data_index:
        raise HTTPException(400, "Index not available")

    body = await request.json()
    current = load_settings(state._data_index)

    # Update only provided fields
    for key in FileIndexSettings.__dataclass_fields__:
        if key in body:
            setattr(current, key, body[key])

    save_settings(state._data_index, current)

    # If enabling, start scanner
    if current.enabled and (not state._file_scanner or not state._file_scanner._running):
        state._file_scanner = LocalFileScanner(
            index=state._data_index,
            settings=current,
            semantic_search=state._semantic_search,
        )
        await state._file_scanner.start()

    # If disabling, stop scanner
    if not current.enabled and state._file_scanner and state._file_scanner._running:
        await state._file_scanner.stop()
        state._file_scanner = None

    return JSONResponse({
        "settings": current.to_dict(),
        "scanner_status": state._file_scanner.status if state._file_scanner else {"enabled": False, "running": False},
    })


@app.get("/files/status")
async def get_file_index_status():
    """Get file scanner progress and stats."""
    if not state._file_scanner:
        return JSONResponse({"enabled": False, "running": False})
    return JSONResponse(state._file_scanner.status)


@app.post("/files/rescan")
async def trigger_file_rescan():
    """Force a full rescan of local files."""
    from local_files import LocalFileScanner, load_settings
    if not state._data_index:
        raise HTTPException(400, "Index not available")

    settings = load_settings(state._data_index)
    if not settings.enabled:
        # Auto-enable if user clicked rescan
        settings.enabled = True

    if not settings.scan_directories:
        raise HTTPException(400, "No directories configured. Add directories first, then rescan.")

    # Stop existing scanner and start fresh
    if state._file_scanner:
        await state._file_scanner.stop()

    state._file_scanner = LocalFileScanner(
        index=state._data_index,
        settings=settings,
        semantic_search=state._semantic_search,
    )
    await state._file_scanner.start(force=True)
    return JSONResponse({"status": "rescan started", "progress": state._file_scanner.status})


@app.get("/files/photos")
async def get_geotagged_photos():
    """Return all photos with GPS coordinates for the map view."""
    if not state._data_index:
        return JSONResponse({"photos": []})

    try:
        rows = state._data_index._conn.execute(
            "SELECT source_id, title, raw, timestamp FROM data_objects "
            "WHERE source = 'local_files' AND raw LIKE '%\"lat\"%' AND raw LIKE '%\"lng\"%' "
            "ORDER BY timestamp DESC"
        ).fetchall()

        photos = []
        for row in rows:
            raw = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            lat = raw.get("lat")
            lng = raw.get("lng")
            if lat is not None and lng is not None:
                photos.append({
                    "path": row[0],
                    "name": row[1],
                    "lat": lat,
                    "lng": lng,
                    "date": row[3] or "",
                })
        return JSONResponse({"photos": photos, "count": len(photos)})
    except Exception as e:
        return JSONResponse({"photos": [], "error": str(e)})


@app.post("/files/migrate-gps")
async def migrate_gps_to_raw():
    """One-time migration: parse GPS from body text into raw JSON field.
    
    Avoids a full rescan — reads existing indexed data and updates in place.
    """
    if not state._data_index:
        raise HTTPException(400, "Index not available")

    import re
    gps_pattern = re.compile(r'GPS:\s*([-\d.]+),\s*([-\d.]+)')

    rows = state._data_index._conn.execute(
        "SELECT id, body, raw FROM data_objects "
        "WHERE source = 'local_files' AND body LIKE '%GPS:%'"
    ).fetchall()

    updated = 0
    for row in rows:
        obj_id, body, raw_str = row
        match = gps_pattern.search(body or "")
        if not match:
            continue

        raw = json.loads(raw_str) if isinstance(raw_str, str) else (raw_str or {})
        if "lat" in raw and "lng" in raw:
            continue  # Already migrated

        raw["lat"] = float(match.group(1))
        raw["lng"] = float(match.group(2))

        state._data_index._conn.execute(
            "UPDATE data_objects SET raw = ? WHERE id = ?",
            (json.dumps(raw), obj_id)
        )
        updated += 1

    state._data_index._conn.commit()
    return JSONResponse({"migrated": updated, "total_with_gps": len(rows)})


@app.get("/files/thumb")
async def get_file_thumbnail(path: str = ""):
    """Serve a photo thumbnail for the map popup."""
    import os
    from pathlib import Path as P

    if not path or not os.path.isfile(path):
        raise HTTPException(404, "File not found")

    # Security: only serve image files from indexed directories
    ext = os.path.splitext(path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tiff", ".heic", ".heif"}:
        raise HTTPException(400, "Not an image file")

    # Verify the file is in an indexed directory
    if state._file_scanner and state._file_scanner._settings.scan_directories:
        allowed = False
        for d in state._file_scanner._settings.scan_directories:
            if path.startswith(d):
                allowed = True
                break
        if not allowed:
            raise HTTPException(403, "File not in indexed directories")

    # Generate thumbnail on the fly (max 400px)
    try:
        from PIL import Image
        import io

        with Image.open(path) as img:
            img.thumbnail((400, 400))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            buf.seek(0)
            from starlette.responses import StreamingResponse
            return StreamingResponse(buf, media_type="image/jpeg")
    except Exception:
        raise HTTPException(500, "Failed to generate thumbnail")


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
    # Globals managed via state module
    
    calendar_connected = state._google_calendar is not None and state._google_calendar.connected
    gmail_connected = state._gmail_connector is not None
    
    # Check env vars for other services
    github_connected = bool(os.environ.get("GITHUB_TOKEN"))
    jira_connected = bool(os.environ.get("JIRA_API_TOKEN") and os.environ.get("JIRA_URL"))
    slack_connected = bool(os.environ.get("SLACK_BOT_TOKEN"))
    
    # Use state._google_connected_services to track which Google services are authorized
    status_map = {
        "gmail": gmail_connected or 'gmail' in state._google_connected_services,
        "google_calendar": calendar_connected or 'calendar' in state._google_connected_services,
        "google_drive": 'drive' in state._google_connected_services,
        "google_contacts": 'contacts' in state._google_connected_services,
        "google_photos": 'photos' in state._google_connected_services,
        "google_sheets": 'sheets' in state._google_connected_services,
        "google_slides": 'slides' in state._google_connected_services,
        "github": github_connected,
        "jira": jira_connected,
        "slack": slack_connected,
    }
    
    # Also check credential store for stored tokens
    try:
        store = state.get_cred_store()
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

@app.get("/api/setup-status")
async def setup_status():
    """Lightweight first-run check — tells the UI what the user still needs to configure."""
    from llm_factory import get_llm_mode
    llm_mode = get_llm_mode()
    has_llm = llm_mode != "none"
    
    # Which LLM provider is set
    llm_provider = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        llm_provider = "anthropic"
    elif os.environ.get("OPENAI_API_KEY"):
        llm_provider = "openai"
    elif llm_mode == "proxy":
        llm_provider = "proxy"
    
    # Count connected services
    connected = []
    try:
        credential_store = get_credential_store()
        connected = credential_store.list_providers()
    except Exception:
        pass
    
    return {
        "ready": has_llm,
        "llm_configured": has_llm,
        "llm_provider": llm_provider,
        "connected_services": connected,
        "needs_setup": not has_llm,
    }


class ApiKeyRequest(BaseModel):
    """Request to set an API key."""
    provider: str  # "anthropic" or "openai"
    api_key: str


@app.post("/api/set-api-key")
async def set_api_key(req: ApiKeyRequest):
    """Set the LLM API key at runtime and persist to .env file."""
    if req.provider not in ("anthropic", "openai"):
        raise HTTPException(status_code=400, detail="Provider must be 'anthropic' or 'openai'")
    
    if not req.api_key or len(req.api_key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key")
    
    # Set in current process
    env_var = "ANTHROPIC_API_KEY" if req.provider == "anthropic" else "OPENAI_API_KEY"
    os.environ[env_var] = req.api_key
    
    # Persist to .env file so it survives restarts
    env_path = Path(__file__).parent / ".env"
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text().splitlines()
    
    # Replace or append
    found = False
    for i, line in enumerate(existing_lines):
        if line.startswith(f"{env_var}="):
            existing_lines[i] = f"{env_var}={req.api_key}"
            found = True
            break
    if not found:
        existing_lines.append(f"{env_var}={req.api_key}")
    
    env_path.write_text("\n".join(existing_lines) + "\n")
    
    return {"success": True, "provider": req.provider, "message": f"{env_var} configured and saved."}


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



@app.get("/primitives")
async def list_primitives():
    """List all primitives and their available providers."""
    resolver = state.get_resolver()
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
    resolver = state.get_resolver()
    
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
    resolver = state.get_resolver()
    
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
    resolver = state.get_resolver()
    
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


# Serve static files (CSS, JS, images)
ui_dir = Path(__file__).parent / "ui"
if ui_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(ui_dir)), name="ui")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
