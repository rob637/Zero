"""
Telic OAuth & Credential Routes

Handles OAuth popup flows, token exchange, credential storage,
and provider management.
"""
import os
import json
import html
import time
from typing import Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse

import server_state as ss
from server_state import SaveCredentialRequest, OAuthInitRequest

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_OAUTH_REDIRECT_URI = "http://127.0.0.1:8000/oauth/callback"
_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# OAuth HTML page helper — eliminates duplication across 11 callback pages
# ---------------------------------------------------------------------------

def _oauth_page(
    title: str,
    heading: str,
    message: str,
    provider: str,
    *,
    success: bool = True,
    status_code: int = 200,
) -> HTMLResponse:
    """Render an OAuth callback popup page.

    All user-facing values are auto-escaped.  The page posts a message
    to the opener window and auto-closes after a short delay.
    """
    safe_heading = html.escape(heading)
    safe_message = html.escape(message)
    safe_provider = html.escape(provider)
    event_type = "oauth_success" if success else "oauth_error"
    icon = "✓" if success else "✗"
    delay = 1500 if success else 2000

    body = f"""<!DOCTYPE html>
<html>
<head>
    <title>{html.escape(title)}</title>
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
        .icon {{ font-size: 48px; margin-bottom: 16px; }}
        h2 {{ margin-bottom: 8px; }}
        p {{ color: #a1a1aa; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">{icon}</div>
        <h2>{safe_heading}</h2>
        <p>{safe_message}</p>
        <p>You can close this window.</p>
    </div>
    <script>
        if (window.opener) {{
            window.opener.postMessage({{
                type: '{event_type}',
                provider: '{safe_provider}'
            }}, window.location.origin);
        }}
        setTimeout(() => window.close(), {delay});
    </script>
</body>
</html>"""
    return HTMLResponse(body, status_code=status_code)


@router.get("/credentials")
async def list_credentials():
    """
    List all stored credentials (without exposing secrets).
    
    Returns provider names, types, and status - NOT the actual credentials.
    """
    store = ss.get_cred_store()
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


@router.post("/credentials")
async def save_credential(req: SaveCredentialRequest):
    """
    Save a credential (API key or token).
    
    Credentials are stored encrypted on disk.
    """
    store = ss.get_cred_store()
    
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


@router.delete("/credentials/{provider}")
async def delete_credential(provider: str):
    """Delete a stored credential."""
    store = ss.get_cred_store()
    
    if store.delete(provider):
        return JSONResponse({"success": True, "message": f"Deleted credential for {provider}"})
    else:
        return JSONResponse(
            {"success": False, "error": f"No credential found for {provider}"},
            status_code=404,
        )


@router.get("/credentials/{provider}/status")
async def credential_status(provider: str):
    """Check credential status for a provider."""
    store = ss.get_cred_store()
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

@router.get("/oauth/start/{provider}")
async def oauth_start(provider: str, scopes: Optional[str] = None):
    """
    Start OAuth flow - returns URL to open in popup.
    
    The popup will redirect to /oauth/callback which handles the token exchange
    and closes the popup with a message to the parent window.
    """
    _purge_expired_oauth_states()
    from connectors.oauth_flow import OAUTH_PROVIDERS
    
    if provider not in OAUTH_PROVIDERS:
        return JSONResponse(
            {"error": f"Unknown OAuth provider: {provider}"},
            status_code=400,
        )
    
    try:
        # For Google, use GoogleAuth which handles credentials from file
        if provider == "google":
            auth = ss.get_google_auth()
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
                redirect_uri=_OAUTH_REDIRECT_URI,
            )
            
            state = secrets.token_urlsafe(32)
            auth_url, _ = flow.authorization_url(
                state=state,
                access_type="offline",
                prompt="consent",
            )
            
            # Store state for callback
            ss._oauth_pending_states[state] = {
                "provider": "google", 
                "flow": flow,
                "scopes": resolved_scopes,
                "created_at": time.time(),
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
                
                auth_url = (
                    f"https://discord.com/api/oauth2/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={_OAUTH_REDIRECT_URI}"
                    f"&response_type=code"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                ss._oauth_pending_states[state] = {
                    "provider": "discord",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "created_at": time.time(),
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
                
                auth_url = (
                    f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={_OAUTH_REDIRECT_URI}"
                    f"&response_type=code"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                ss._oauth_pending_states[state] = {
                    "provider": "microsoft",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "created_at": time.time(),
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
                
                auth_url = (
                    f"https://slack.com/oauth/v2/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={_OAUTH_REDIRECT_URI}"
                    f"&user_scope={scope_str}"
                    f"&state={state}"
                )
                
                ss._oauth_pending_states[state] = {
                    "provider": "slack",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "created_at": time.time(),
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
                
                auth_url = (
                    f"https://github.com/login/oauth/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={_OAUTH_REDIRECT_URI}"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                ss._oauth_pending_states[state] = {
                    "provider": "github",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "created_at": time.time(),
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
                
                auth_url = (
                    f"https://accounts.spotify.com/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={_OAUTH_REDIRECT_URI}"
                    f"&response_type=code"
                    f"&scope={scope_str}"
                    f"&state={state}"
                )
                
                ss._oauth_pending_states[state] = {
                    "provider": "spotify",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "created_at": time.time(),
                }
                
                return JSONResponse({
                    "auth_url": auth_url,
                    "state": state,
                    "provider": provider,
                })
        
        # For any other provider in OAUTH_PROVIDERS, check env vars
        env_prefix = provider.upper()
        # Handle special env var naming
        env_map = {"atlassian": "ATLASSIAN", "jira": "ATLASSIAN"}
        env_name = env_map.get(provider, env_prefix)
        
        client_id = os.environ.get(f"{env_name}_CLIENT_ID")
        client_secret = os.environ.get(f"{env_name}_CLIENT_SECRET")
        
        if client_id and client_secret:
            import secrets as _secrets
            state = _secrets.token_urlsafe(32)
            
            config = OAUTH_PROVIDERS[provider]
            
            # Build scopes
            scope_list = config.scopes.get("all", list(config.scopes.values())[0]) if len(config.scopes) > 0 else []
            scope_str = "%20".join(scope_list) if scope_list else ""
            
            redirect_uri = _OAUTH_REDIRECT_URI
            from urllib.parse import urlencode, quote
            
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": state,
            }
            if scope_str:
                params["scope"] = " ".join(scope_list)
            
            # Add provider-specific extra params
            params.update(config.extra_auth_params)
            
            auth_url = f"{config.auth_url}?{urlencode(params)}"
            
            ss._oauth_pending_states[state] = {
                "provider": provider,
                "client_id": client_id,
                "client_secret": client_secret,
                "created_at": time.time(),
            }
            
            print(f"[OAUTH] Starting {provider} OAuth flow")
            
            return JSONResponse({
                "auth_url": auth_url,
                "state": state,
                "provider": provider,
            })
        
        return JSONResponse({
            "error": f"No credentials configured for {provider}. Add {env_name}_CLIENT_ID and {env_name}_CLIENT_SECRET to .env",
            "needs_setup": True,
        }, status_code=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )

# Store pending OAuth states for callback
ss._oauth_pending_states: Dict[str, Any] = {}


def _purge_expired_oauth_states() -> None:
    """Remove expired entries from the pending states dict to prevent unbounded growth."""
    now = time.time()
    expired = [k for k, v in ss._oauth_pending_states.items()
               if now - v.get("created_at", 0) > _OAUTH_STATE_TTL_SECONDS]
    for k in expired:
        del ss._oauth_pending_states[k]


@router.get("/oauth/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    """
    OAuth callback handler.
    
    This page is loaded in the popup window after user authorizes.
    It exchanges the code for tokens, stores them, and closes the popup.
    """
    if error:
        return _oauth_page(
            "Authorization Failed", "Authorization Failed",
            str(error), "unknown", success=False,
        )
    
    if not code or not state:
        return _oauth_page(
            "Missing Parameters", "Missing authorization code or state",
            "The callback was missing required parameters.", "unknown",
            success=False,
        )
    
    try:
        # Check our pending states first, then fall back to generic oauth_flow
        if state not in ss._oauth_pending_states:
            # Try the generic OAuth flow handler (has its own state tracking)
            from connectors.oauth_flow import get_oauth_flow
            
            try:
                flow = get_oauth_flow()
                tokens = await flow.handle_callback(code, state)
                
                if not tokens:
                    raise Exception("Failed to exchange authorization code")
                
                provider_used = tokens.get("provider", "unknown")
                
                store = ss.get_cred_store()
                store.save_token(
                    provider=provider_used,
                    access_token=tokens.get("access_token"),
                    refresh_token=tokens.get("refresh_token"),
                    expires_in=tokens.get("expires_in"),
                    scopes=tokens.get("scope", "").split() if tokens.get("scope") else [],
                )
                
                return _oauth_page(
                    "Authorization Successful", "Connected!",
                    "Account linked successfully.", provider_used,
                )
            except (ValueError, KeyError):
                return _oauth_page(
                    "Invalid State", "Invalid or expired authorization",
                    "The authorization request was not found or has expired. Please try again.",
                    "unknown", success=False,
                )
        
        pending = ss._oauth_pending_states.pop(state)
        created_at = pending.get("created_at", 0)
        if time.time() - created_at > _OAUTH_STATE_TTL_SECONDS:
            return _oauth_page(
                "Expired", "Authorization Expired",
                "This authorization request has expired. Please try again.",
                pending.get("provider", "unknown"), success=False,
            )
        
        provider_used = pending["provider"]
        
        if provider_used == "google":
            # Exchange code using Google's flow
            flow = pending["flow"]
            flow.fetch_token(code=code)
            creds = flow.credentials
            
            # Store tokens using GoogleAuth
            auth = ss.get_google_auth()
            auth._creds = creds
            auth._save_token()
            
            # Also save to credential_store so /connectors endpoint sees Google as connected
            store = ss.get_cred_store()
            store.save_token(
                provider="google",
                access_token=creds.token or "",
                refresh_token=creds.refresh_token,
                expires_in=3600,
                scopes=list(creds.scopes or []),
            )
            
            # Connect services with the new credentials
            # Modify globals via state module
            
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
            ss._google_connected_services.clear()
            for scope in token_scopes:
                for key, service in scope_to_service.items():
                    if key in scope.lower():
                        ss._google_connected_services.add(service)
            
            print(f"[OAUTH] Authorized Google services: {ss._google_connected_services}")
            
            has_calendar = 'calendar' in ss._google_connected_services
            has_gmail = 'gmail' in ss._google_connected_services
            
            if has_calendar:
                ss._google_calendar = ss.CalendarConnector(auth)
                await ss._google_calendar.connect()
                print("[OAUTH] Google Calendar connected!")
            
            if has_gmail:
                from connectors.gmail import GmailConnector
                ss._gmail_connector = GmailConnector(auth)
                if await ss._gmail_connector.connect():
                    print("[OAUTH] Gmail connected!")
            
            # Rebuild engine
            ss.get_telic_engine(force_rebuild=True)
            
            # Build a display of connected services
            services_display = []
            for svc in ['calendar', 'gmail', 'drive', 'contacts', 'photos', 'sheets', 'slides']:
                if svc in ss._google_connected_services:
                    services_display.append(f"{svc.title()}: ✓")
            connected_text = " | ".join(services_display) if services_display else "No services"
            
            return _oauth_page(
                "Authorization Successful", "Connected!",
                connected_text, "google",
            )
        
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
                        "redirect_uri": _OAUTH_REDIRECT_URI,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                
                if response.status_code != 200:
                    raise Exception(f"Discord token exchange failed: {response.text}")
                
                tokens = response.json()
            
            # Store tokens
            store = ss.get_cred_store()
            store.save_token(
                provider="discord",
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                expires_in=tokens.get("expires_in"),
                scopes=tokens.get("scope", "").split(),
            )
            store.save_client_credentials(
                provider="discord",
                client_id=client_id,
                client_secret=client_secret,
            )
            
            print(f"[OAUTH] Discord connected!")
            
            return _oauth_page(
                "Discord Connected", "Discord Connected!",
                "Your Discord account is ready.", "discord",
            )
        
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
                        "redirect_uri": _OAUTH_REDIRECT_URI,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                
                if response.status_code != 200:
                    raise Exception(f"Microsoft token exchange failed: {response.text}")
                
                tokens = response.json()
            
            # Store tokens
            store = ss.get_cred_store()
            store.save_token(
                provider="microsoft",
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                expires_in=tokens.get("expires_in"),
                scopes=tokens.get("scope", "").split(),
            )
            store.save_client_credentials(
                provider="microsoft",
                client_id=client_id,
                client_secret=client_secret,
            )
            
            print(f"[OAUTH] Microsoft connected!")
            
            return _oauth_page(
                "Microsoft Connected", "Microsoft Connected!",
                "Outlook, OneDrive, Calendar, Tasks", "microsoft",
            )
        
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
                        "redirect_uri": _OAUTH_REDIRECT_URI,
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
            store = ss.get_cred_store()
            authed_user = tokens.get("authed_user", {})
            store.save_token(
                provider="slack",
                access_token=authed_user.get("access_token") or tokens.get("access_token"),
                refresh_token=authed_user.get("refresh_token") or tokens.get("refresh_token"),
                expires_in=None,  # Slack tokens don't expire
                scopes=(authed_user.get("scope", "") or tokens.get("scope", "")).split(","),
            )
            store.save_client_credentials(
                provider="slack",
                client_id=client_id,
                client_secret=client_secret,
            )
            
            team_name = tokens.get("team", {}).get("name", "Workspace")
            print(f"[OAUTH] Slack connected to {team_name}!")
            
            return _oauth_page(
                "Slack Connected", "Slack Connected!",
                f"Workspace: {team_name}", "slack",
            )
        
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
            store = ss.get_cred_store()
            store.save_token(
                provider="github",
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                expires_in=tokens.get("expires_in"),
                scopes=tokens.get("scope", "").split(","),
            )
            store.save_client_credentials(
                provider="github",
                client_id=client_id,
                client_secret=client_secret,
            )
            
            print(f"[OAUTH] GitHub connected!")
            
            return _oauth_page(
                "GitHub Connected", "GitHub Connected!",
                "Repos, Issues, PRs", "github",
            )
        
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
                        "redirect_uri": _OAUTH_REDIRECT_URI,
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
            store = ss.get_cred_store()
            store.save_token(
                provider="spotify",
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                expires_in=tokens.get("expires_in"),
                scopes=tokens.get("scope", "").split(),
            )
            store.save_client_credentials(
                provider="spotify",
                client_id=client_id,
                client_secret=client_secret,
            )
            
            print(f"[OAUTH] Spotify connected!")
            
            return _oauth_page(
                "Spotify Connected", "Spotify Connected!",
                "Music playback enabled", "spotify",
            )
        
        else:
            # Generic OAuth 2.0 token exchange for any other provider
            from connectors.oauth_flow import OAUTH_PROVIDERS as _OAUTH_PROVIDERS
            import httpx
            
            client_id = pending["client_id"]
            client_secret = pending["client_secret"]
            config = _OAUTH_PROVIDERS.get(provider_used)
            
            if not config:
                raise Exception(f"No OAuth config for {provider_used}")
            
            # Some providers (Notion, Zoom) use Basic auth for token exchange
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            }
            
            token_data = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": _OAUTH_REDIRECT_URI,
            }
            
            # Notion uses Basic auth instead of client_secret in body
            if provider_used == "notion":
                import base64
                auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
                headers["Authorization"] = f"Basic {auth_header}"
                del token_data["client_secret"]
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    config.token_url,
                    data=token_data,
                    headers=headers,
                )
                
                if response.status_code != 200:
                    raise Exception(f"{config.name} token exchange failed: {response.text}")
                
                tokens = response.json()
            
            if "error" in tokens:
                raise Exception(f"{config.name} error: {tokens.get('error_description', tokens.get('error'))}")
            
            # Store tokens
            store = ss.get_cred_store()
            store.save_token(
                provider=provider_used,
                access_token=tokens.get("access_token"),
                refresh_token=tokens.get("refresh_token"),
                expires_in=tokens.get("expires_in"),
                scopes=tokens.get("scope", "").split() if tokens.get("scope") else [],
            )
            store.save_client_credentials(
                provider=provider_used,
                client_id=client_id,
                client_secret=client_secret,
            )
            
            print(f"[OAUTH] {config.name} connected!")
            
            return _oauth_page(
                f"{config.name} Connected", f"{config.name} Connected!",
                "Account linked successfully.", provider_used,
            )
        
    except Exception as e:
        return _oauth_page(
            "Authorization Failed", "Authorization Failed",
            str(e), "unknown", success=False,
        )


# Routes


@router.get("/oauth/providers")
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


@router.get("/oauth/status")
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


@router.post("/oauth/{provider}/init")
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


@router.get("/oauth/generic/callback")
async def oauth_callback_get(code: str, state: str):
    """
    OAuth callback endpoint (GET) for generic oauth_flow providers.
    
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


@router.post("/oauth/generic/callback")
async def oauth_callback_post(code: str, state: str):
    """
    OAuth callback endpoint (POST) for generic oauth_flow providers.
    
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


@router.get("/oauth/{provider}/status")
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


@router.post("/oauth/{provider}/refresh")
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


@router.delete("/oauth/{provider}")
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
