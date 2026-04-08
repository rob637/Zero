"""
Ziggy OAuth Broker - Central Authentication Service

Deploy this to handle OAuth for all users.
Users connect through this broker instead of registering their own apps.

Deployment Options:
    1. Vercel: `vercel deploy`
    2. Railway: Push to Railway
    3. Self-hosted: `uvicorn broker:app --host 0.0.0.0 --port 8080`

Environment Variables Required:
    # Google
    GOOGLE_CLIENT_ID=xxx
    GOOGLE_CLIENT_SECRET=xxx
    
    # Microsoft
    MICROSOFT_CLIENT_ID=xxx
    MICROSOFT_CLIENT_SECRET=xxx
    
    # Slack
    SLACK_CLIENT_ID=xxx
    SLACK_CLIENT_SECRET=xxx
    
    # Discord
    DISCORD_CLIENT_ID=xxx
    DISCORD_CLIENT_SECRET=xxx
    
    # GitHub
    GITHUB_CLIENT_ID=xxx
    GITHUB_CLIENT_SECRET=xxx
    
    # Security
    BROKER_SECRET=xxx  # For signing state tokens
"""

import os
import secrets
import hashlib
import time
import json
import base64
from urllib.parse import urlencode, quote, parse_qs
from typing import Optional, Dict, Any
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = FastAPI(
    title="Ziggy OAuth Broker",
    description="Central OAuth authentication for Ziggy AI OS",
    version="1.0.0",
)

# CORS for local Ziggy instances
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000", "https://*.ziggy.ai"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Provider Configuration
# =============================================================================

@dataclass
class OAuthProvider:
    """OAuth provider configuration."""
    name: str
    client_id_env: str
    client_secret_env: str
    authorize_url: str
    token_url: str
    scopes: list
    extra_params: dict = None
    
    @property
    def client_id(self) -> Optional[str]:
        return os.environ.get(self.client_id_env)
    
    @property
    def client_secret(self) -> Optional[str]:
        return os.environ.get(self.client_secret_env)
    
    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


PROVIDERS = {
    "google": OAuthProvider(
        name="Google",
        client_id_env="GOOGLE_CLIENT_ID",
        client_secret_env="GOOGLE_CLIENT_SECRET",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes=[
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/contacts.readonly",
            "https://www.googleapis.com/auth/photoslibrary.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/presentations",
        ],
        extra_params={"access_type": "offline", "prompt": "consent"},
    ),
    
    "microsoft": OAuthProvider(
        name="Microsoft",
        client_id_env="MICROSOFT_CLIENT_ID",
        client_secret_env="MICROSOFT_CLIENT_SECRET",
        authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scopes=[
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
        ],
    ),
    
    "slack": OAuthProvider(
        name="Slack",
        client_id_env="SLACK_CLIENT_ID",
        client_secret_env="SLACK_CLIENT_SECRET",
        authorize_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes=[
            "channels:read",
            "channels:history",
            "chat:write",
            "users:read",
            "users:read.email",
            "team:read",
            "files:read",
            "reactions:read",
            "reactions:write",
            "im:read",
            "im:history",
            "mpim:read",
            "mpim:history",
            "groups:read",
            "groups:history",
        ],
    ),
    
    "discord": OAuthProvider(
        name="Discord",
        client_id_env="DISCORD_CLIENT_ID",
        client_secret_env="DISCORD_CLIENT_SECRET",
        authorize_url="https://discord.com/api/oauth2/authorize",
        token_url="https://discord.com/api/oauth2/token",
        scopes=["identify", "email", "guilds"],
    ),
    
    "github": OAuthProvider(
        name="GitHub",
        client_id_env="GITHUB_CLIENT_ID",
        client_secret_env="GITHUB_CLIENT_SECRET",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes=["user", "repo", "read:org"],
    ),
    
    "spotify": OAuthProvider(
        name="Spotify",
        client_id_env="SPOTIFY_CLIENT_ID",
        client_secret_env="SPOTIFY_CLIENT_SECRET",
        authorize_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        scopes=[
            "user-read-private",
            "user-read-email",
            "user-read-playback-state",
            "user-modify-playback-state",
            "user-read-currently-playing",
            "playlist-read-private",
            "playlist-modify-public",
            "playlist-modify-private",
        ],
    ),
    
    "notion": OAuthProvider(
        name="Notion",
        client_id_env="NOTION_CLIENT_ID",
        client_secret_env="NOTION_CLIENT_SECRET",
        authorize_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes=[],  # Notion doesn't use scopes, uses workspace access
        extra_params={"owner": "user"},
    ),
    
    "todoist": OAuthProvider(
        name="Todoist",
        client_id_env="TODOIST_CLIENT_ID",
        client_secret_env="TODOIST_CLIENT_SECRET",
        authorize_url="https://todoist.com/oauth/authorize",
        token_url="https://todoist.com/oauth/access_token",
        scopes=["data:read_write"],
    ),
    
    "zoom": OAuthProvider(
        name="Zoom",
        client_id_env="ZOOM_CLIENT_ID",
        client_secret_env="ZOOM_CLIENT_SECRET",
        authorize_url="https://zoom.us/oauth/authorize",
        token_url="https://zoom.us/oauth/token",
        scopes=["meeting:read", "meeting:write", "user:read"],
    ),
    
    "linear": OAuthProvider(
        name="Linear",
        client_id_env="LINEAR_CLIENT_ID",
        client_secret_env="LINEAR_CLIENT_SECRET",
        authorize_url="https://linear.app/oauth/authorize",
        token_url="https://api.linear.app/oauth/token",
        scopes=["read", "write", "issues:create"],
    ),
}


# =============================================================================
# State Management (in production, use Redis)
# =============================================================================

# In-memory state store (use Redis in production)
_pending_states: Dict[str, Dict] = {}
BROKER_SECRET = os.environ.get("BROKER_SECRET", secrets.token_hex(32))


def create_state(provider: str, callback_url: str) -> str:
    """Create a signed state token."""
    state_id = secrets.token_urlsafe(32)
    timestamp = int(time.time())
    
    _pending_states[state_id] = {
        "provider": provider,
        "callback_url": callback_url,
        "timestamp": timestamp,
    }
    
    return state_id


def verify_state(state: str) -> Optional[Dict]:
    """Verify and consume a state token."""
    if state not in _pending_states:
        return None
    
    data = _pending_states.pop(state)
    
    # Expire after 10 minutes
    if time.time() - data["timestamp"] > 600:
        return None
    
    return data


# =============================================================================
# Routes
# =============================================================================

@app.get("/")
async def root():
    """Health check and provider status."""
    configured = [name for name, p in PROVIDERS.items() if p.is_configured]
    return {
        "service": "Ziggy OAuth Broker",
        "status": "healthy",
        "configured_providers": configured,
        "version": "1.0.0",
    }


@app.get("/providers")
async def list_providers():
    """List all available providers and their status."""
    return {
        name: {
            "name": p.name,
            "configured": p.is_configured,
            "scopes": p.scopes,
        }
        for name, p in PROVIDERS.items()
    }


@app.get("/connect/{provider}")
async def start_oauth(
    provider: str,
    callback: str = Query(..., description="URL to redirect back to after OAuth"),
    scopes: Optional[str] = Query(None, description="Comma-separated scopes to request"),
):
    """
    Start OAuth flow for a provider.
    
    Redirects user to provider's authorization page.
    After authorization, redirects back to callback URL with tokens.
    """
    if provider not in PROVIDERS:
        raise HTTPException(404, f"Unknown provider: {provider}")
    
    p = PROVIDERS[provider]
    
    if not p.is_configured:
        raise HTTPException(
            503,
            f"{p.name} is not configured on this broker. "
            f"Contact the broker administrator or use self-hosted mode."
        )
    
    # Create state for CSRF protection
    state = create_state(provider, callback)
    
    # Build authorization URL
    redirect_uri = os.environ.get(
        "BROKER_REDIRECT_URI",
        "https://auth.ziggy.ai/callback"  # Production
    )
    
    # For local dev, use localhost
    if os.environ.get("DEV_MODE"):
        redirect_uri = "http://localhost:8080/callback"
    
    # Use custom scopes if provided, otherwise default
    requested_scopes = scopes.split(",") if scopes else p.scopes
    
    params = {
        "client_id": p.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(requested_scopes),
        "state": state,
    }
    
    # Add provider-specific params
    if p.extra_params:
        params.update(p.extra_params)
    
    auth_url = f"{p.authorize_url}?{urlencode(params)}"
    
    return RedirectResponse(auth_url)


@app.get("/callback")
async def oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """
    OAuth callback handler.
    
    Exchanges code for tokens and redirects back to user's local Ziggy.
    """
    if error:
        # OAuth error
        return HTMLResponse(f"""
            <html>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>❌ Authorization Failed</h1>
                <p>{error}: {error_description or 'Unknown error'}</p>
                <p>You can close this window.</p>
            </body>
            </html>
        """, status_code=400)
    
    if not code or not state:
        raise HTTPException(400, "Missing code or state")
    
    # Verify state
    state_data = verify_state(state)
    if not state_data:
        raise HTTPException(400, "Invalid or expired state")
    
    provider = state_data["provider"]
    callback_url = state_data["callback_url"]
    p = PROVIDERS[provider]
    
    # Exchange code for tokens
    redirect_uri = os.environ.get(
        "BROKER_REDIRECT_URI",
        "https://auth.ziggy.ai/callback"
    )
    if os.environ.get("DEV_MODE"):
        redirect_uri = "http://localhost:8080/callback"
    
    import httpx
    
    token_data = {
        "client_id": p.client_id,
        "client_secret": p.client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    
    headers = {"Accept": "application/json"}
    
    # GitHub needs special handling
    if provider == "github":
        headers["Accept"] = "application/json"
    
    # Notion needs basic auth
    if provider == "notion":
        import base64
        auth = base64.b64encode(f"{p.client_id}:{p.client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {auth}"
        token_data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            p.token_url,
            data=token_data,
            headers=headers,
        )
    
    if response.status_code != 200:
        return HTMLResponse(f"""
            <html>
            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                <h1>❌ Token Exchange Failed</h1>
                <p>Status: {response.status_code}</p>
                <p>{response.text}</p>
                <p>You can close this window.</p>
            </body>
            </html>
        """, status_code=400)
    
    # Parse token response
    if "application/json" in response.headers.get("content-type", ""):
        tokens = response.json()
    else:
        # Some providers return form-encoded
        tokens = dict(parse_qs(response.text))
        tokens = {k: v[0] if len(v) == 1 else v for k, v in tokens.items()}
    
    # Build callback URL with tokens
    # Encode tokens as base64 JSON for safe URL transport
    token_payload = {
        "provider": provider,
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_in": tokens.get("expires_in"),
        "scope": tokens.get("scope"),
        "token_type": tokens.get("token_type", "Bearer"),
    }
    
    encoded_tokens = base64.urlsafe_b64encode(
        json.dumps(token_payload).encode()
    ).decode()
    
    # Redirect back to user's local Ziggy
    separator = "&" if "?" in callback_url else "?"
    redirect_url = f"{callback_url}{separator}tokens={encoded_tokens}&provider={provider}"
    
    return RedirectResponse(redirect_url)


@app.post("/refresh/{provider}")
async def refresh_token(provider: str, request: Request):
    """
    Refresh an access token.
    
    Body: {"refresh_token": "..."}
    Returns: {"access_token": "...", "expires_in": ...}
    """
    if provider not in PROVIDERS:
        raise HTTPException(404, f"Unknown provider: {provider}")
    
    p = PROVIDERS[provider]
    
    if not p.is_configured:
        raise HTTPException(503, f"{p.name} is not configured")
    
    body = await request.json()
    refresh_token = body.get("refresh_token")
    
    if not refresh_token:
        raise HTTPException(400, "Missing refresh_token")
    
    import httpx
    
    token_data = {
        "client_id": p.client_id,
        "client_secret": p.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            p.token_url,
            data=token_data,
            headers={"Accept": "application/json"},
        )
    
    if response.status_code != 200:
        raise HTTPException(400, f"Token refresh failed: {response.text}")
    
    tokens = response.json()
    
    return {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),  # Some providers rotate
        "expires_in": tokens.get("expires_in"),
    }


# =============================================================================
# Vercel / Serverless Entry Point
# =============================================================================

# For Vercel, export the app
handler = app
