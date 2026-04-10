"""
OAuth 2.0 Flow Manager

Web-based OAuth flow for connecting services. This module handles:
- Authorization URL generation with PKCE
- Callback handling and token exchange
- Token storage via CredentialStore
- State management for CSRF protection

Supported Providers:
- Google (Gmail, Calendar, Drive, Contacts)
- Microsoft (Outlook, Calendar, OneDrive, To-Do, Teams)
- Slack
- GitHub
- Discord
- Spotify
- Dropbox
- Atlassian (Jira)

Usage:
    from apex.connectors.oauth_flow import OAuthFlow, get_oauth_flow
    
    flow = get_oauth_flow()
    
    # Start OAuth flow
    auth_url = flow.get_auth_url("google", scopes=["gmail", "calendar"])
    # Redirect user to auth_url
    
    # Handle callback
    await flow.handle_callback(code, state)
    # Tokens are now stored in CredentialStore
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, parse_qs, urlparse

logger = logging.getLogger(__name__)

# Try to import httpx for async HTTP requests
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None

# Import our credential store
from .credentials import CredentialStore, get_credential_store, CredentialType


# ============================================================
#  OAUTH PROVIDER CONFIGURATIONS
# ============================================================

@dataclass
class OAuthProviderConfig:
    """Configuration for an OAuth provider."""
    name: str
    auth_url: str
    token_url: str
    scopes: Dict[str, List[str]]  # service -> scopes mapping
    supports_pkce: bool = True
    extra_auth_params: Dict[str, str] = field(default_factory=dict)
    extra_token_params: Dict[str, str] = field(default_factory=dict)


OAUTH_PROVIDERS: Dict[str, OAuthProviderConfig] = {
    "google": OAuthProviderConfig(
        name="Google",
        auth_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes={
            "gmail": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
            "calendar": [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ],
            "drive": [
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/drive.file",
            ],
            "contacts": [
                "https://www.googleapis.com/auth/contacts.readonly",
                "https://www.googleapis.com/auth/contacts",
            ],
            "sheets": [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/spreadsheets.readonly",
            ],
            "slides": [
                "https://www.googleapis.com/auth/presentations",
                "https://www.googleapis.com/auth/presentations.readonly",
            ],
            "photos": [
                "https://www.googleapis.com/auth/photoslibrary.readonly",
            ],
            "youtube": [
                "https://www.googleapis.com/auth/youtube.readonly",
                "https://www.googleapis.com/auth/youtube",
            ],
            # Combined scopes for all Google services
            "all": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/drive.file",
                "https://www.googleapis.com/auth/contacts.readonly",
                "https://www.googleapis.com/auth/youtube.readonly",
            ],
        },
        supports_pkce=True,
        extra_auth_params={
            "access_type": "offline",  # Get refresh token
            "prompt": "consent",  # Force consent for refresh token
        },
    ),
    
    "microsoft": OAuthProviderConfig(
        name="Microsoft",
        auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scopes={
            "mail": [
                "https://graph.microsoft.com/Mail.Read",
                "https://graph.microsoft.com/Mail.Send",
                "https://graph.microsoft.com/Mail.ReadWrite",
            ],
            "calendar": [
                "https://graph.microsoft.com/Calendars.Read",
                "https://graph.microsoft.com/Calendars.ReadWrite",
            ],
            "onedrive": [
                "https://graph.microsoft.com/Files.Read",
                "https://graph.microsoft.com/Files.ReadWrite",
            ],
            "tasks": [
                "https://graph.microsoft.com/Tasks.Read",
                "https://graph.microsoft.com/Tasks.ReadWrite",
            ],
            "teams": [
                "https://graph.microsoft.com/Chat.Read",
                "https://graph.microsoft.com/Chat.ReadWrite",
                "https://graph.microsoft.com/Team.ReadBasic.All",
            ],
            "contacts": [
                "https://graph.microsoft.com/Contacts.Read",
            ],
            # Combined for all Microsoft services
            "all": [
                "https://graph.microsoft.com/User.Read",
                "https://graph.microsoft.com/Mail.Read",
                "https://graph.microsoft.com/Mail.Send",
                "https://graph.microsoft.com/Calendars.ReadWrite",
                "https://graph.microsoft.com/Files.ReadWrite",
                "https://graph.microsoft.com/Tasks.ReadWrite",
                "offline_access",  # For refresh token
            ],
        },
        supports_pkce=True,
        extra_auth_params={
            "response_mode": "query",
        },
    ),
    
    "slack": OAuthProviderConfig(
        name="Slack",
        auth_url="https://slack.com/oauth/v2/authorize",
        token_url="https://slack.com/api/oauth.v2.access",
        scopes={
            "bot": [
                "channels:history",
                "channels:read",
                "chat:write",
                "users:read",
                "im:history",
                "im:read",
            ],
            "user": [
                "channels:history",
                "channels:read",
                "users:read",
            ],
        },
        supports_pkce=False,  # Slack doesn't support PKCE
    ),
    
    "github": OAuthProviderConfig(
        name="GitHub",
        auth_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes={
            "repo": ["repo"],
            "user": ["user", "read:user"],
            "issues": ["repo"],
            "pulls": ["repo", "pull_request:write"],
            "all": ["repo", "user", "read:org", "workflow"],
        },
        supports_pkce=False,
    ),
    
    "discord": OAuthProviderConfig(
        name="Discord",
        auth_url="https://discord.com/api/oauth2/authorize",
        token_url="https://discord.com/api/oauth2/token",
        scopes={
            "bot": ["identify", "guilds", "messages.read"],
            "user": ["identify", "email"],
        },
        supports_pkce=True,
    ),
    
    "spotify": OAuthProviderConfig(
        name="Spotify",
        auth_url="https://accounts.spotify.com/authorize",
        token_url="https://accounts.spotify.com/api/token",
        scopes={
            "playback": [
                "user-read-playback-state",
                "user-modify-playback-state",
                "user-read-currently-playing",
            ],
            "library": [
                "user-library-read",
                "user-library-modify",
            ],
            "playlists": [
                "playlist-read-private",
                "playlist-modify-public",
                "playlist-modify-private",
            ],
            "all": [
                "user-read-playback-state",
                "user-modify-playback-state",
                "user-read-currently-playing",
                "user-library-read",
                "playlist-read-private",
            ],
        },
        supports_pkce=True,
    ),
    
    "dropbox": OAuthProviderConfig(
        name="Dropbox",
        auth_url="https://www.dropbox.com/oauth2/authorize",
        token_url="https://api.dropboxapi.com/oauth2/token",
        scopes={},  # Dropbox scopes are set in app console, not in auth URL
        supports_pkce=True,
        extra_auth_params={
            "token_access_type": "offline",  # For refresh tokens
        },
    ),
    
    "atlassian": OAuthProviderConfig(
        name="Atlassian",
        auth_url="https://auth.atlassian.com/authorize",
        token_url="https://auth.atlassian.com/oauth/token",
        scopes={
            "jira": [
                "read:jira-work",
                "write:jira-work",
                "read:jira-user",
            ],
            "confluence": [
                "read:confluence-content.all",
                "write:confluence-content",
            ],
        },
        supports_pkce=True,
        extra_auth_params={
            "audience": "api.atlassian.com",
            "prompt": "consent",
        },
    ),
    
    "todoist": OAuthProviderConfig(
        name="Todoist",
        auth_url="https://todoist.com/oauth/authorize",
        token_url="https://todoist.com/oauth/access_token",
        scopes={
            "all": ["data:read_write,data:delete"],
        },
        supports_pkce=False,
    ),
    
    "notion": OAuthProviderConfig(
        name="Notion",
        auth_url="https://api.notion.com/v1/oauth/authorize",
        token_url="https://api.notion.com/v1/oauth/token",
        scopes={},  # Notion doesn't use scopes in the auth URL
        supports_pkce=False,
        extra_auth_params={
            "owner": "user",
        },
        extra_token_params={},
    ),
    
    "hubspot": OAuthProviderConfig(
        name="HubSpot",
        auth_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        scopes={
            "all": [
                "crm.objects.contacts.read",
                "crm.objects.contacts.write",
                "crm.objects.companies.read",
                "crm.objects.deals.read",
                "crm.objects.deals.write",
            ],
        },
        supports_pkce=False,
    ),
    
    "zoom": OAuthProviderConfig(
        name="Zoom",
        auth_url="https://zoom.us/oauth/authorize",
        token_url="https://zoom.us/oauth/token",
        scopes={
            "all": [
                "meeting:read",
                "meeting:write",
                "user:read",
            ],
        },
        supports_pkce=True,
    ),
    
    "reddit": OAuthProviderConfig(
        name="Reddit",
        auth_url="https://www.reddit.com/api/v1/authorize",
        token_url="https://www.reddit.com/api/v1/access_token",
        scopes={
            "all": [
                "identity",
                "read",
                "submit",
                "subscribe",
                "history",
            ],
        },
        supports_pkce=False,
        extra_auth_params={
            "duration": "permanent",
        },
    ),

    "linkedin": OAuthProviderConfig(
        name="LinkedIn",
        auth_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        scopes={
            "all": [
                "openid",
                "profile",
                "email",
                "w_member_social",
            ],
        },
        supports_pkce=False,
    ),

    "twitter": OAuthProviderConfig(
        name="Twitter",
        auth_url="https://twitter.com/i/oauth2/authorize",
        token_url="https://api.twitter.com/2/oauth2/token",
        scopes={
            "all": [
                "tweet.read",
                "tweet.write",
                "users.read",
                "offline.access",
            ],
        },
        supports_pkce=True,
    ),
}


# ============================================================
#  PENDING AUTH STATE STORAGE
# ============================================================

@dataclass
class PendingAuth:
    """A pending OAuth authorization request."""
    state: str
    provider: str
    services: List[str]
    scopes: List[str]
    redirect_uri: str
    code_verifier: Optional[str]  # For PKCE
    created_at: datetime
    client_id: str
    client_secret: Optional[str]
    
    def is_expired(self, max_age_minutes: int = 10) -> bool:
        """Check if this pending auth has expired."""
        return datetime.utcnow() > self.created_at + timedelta(minutes=max_age_minutes)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "provider": self.provider,
            "services": self.services,
            "scopes": self.scopes,
            "redirect_uri": self.redirect_uri,
            "code_verifier": self.code_verifier,
            "created_at": self.created_at.isoformat(),
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingAuth":
        return cls(
            state=d["state"],
            provider=d["provider"],
            services=d["services"],
            scopes=d["scopes"],
            redirect_uri=d["redirect_uri"],
            code_verifier=d.get("code_verifier"),
            created_at=datetime.fromisoformat(d["created_at"]),
            client_id=d["client_id"],
            client_secret=d.get("client_secret"),
        )


# ============================================================
#  OAUTH FLOW MANAGER
# ============================================================

class OAuthFlow:
    """
    Manages OAuth 2.0 authorization flows.
    
    Supports:
    - Authorization URL generation with PKCE
    - State token management for CSRF protection
    - Token exchange from authorization codes
    - Token storage via CredentialStore
    - Automatic refresh token handling
    """
    
    def __init__(
        self,
        credential_store: Optional[CredentialStore] = None,
        redirect_uri: str = "http://127.0.0.1:8000/oauth/callback",
    ):
        self._credential_store = credential_store or get_credential_store()
        self._redirect_uri = redirect_uri
        self._pending: Dict[str, PendingAuth] = {}  # state -> PendingAuth
        
        # Load pending states from storage
        self._pending_storage_path = Path("~/.apex/oauth_pending").expanduser()
        self._pending_storage_path.mkdir(parents=True, exist_ok=True)
        self._load_pending_states()
    
    def _load_pending_states(self):
        """Load pending auth states from disk."""
        try:
            state_file = self._pending_storage_path / "pending.json"
            if state_file.exists():
                data = json.loads(state_file.read_text())
                for state, pending_dict in data.items():
                    pending = PendingAuth.from_dict(pending_dict)
                    if not pending.is_expired():
                        self._pending[state] = pending
        except Exception as e:
            logger.warning(f"Failed to load pending OAuth states: {e}")
    
    def _save_pending_states(self):
        """Save pending auth states to disk."""
        try:
            state_file = self._pending_storage_path / "pending.json"
            data = {
                state: pending.to_dict() 
                for state, pending in self._pending.items()
                if not pending.is_expired()
            }
            state_file.write_text(json.dumps(data))
        except Exception as e:
            logger.warning(f"Failed to save pending OAuth states: {e}")
    
    def _generate_pkce(self) -> Tuple[str, str]:
        """Generate PKCE code verifier and challenge."""
        # Generate code verifier (43-128 chars, URL-safe)
        code_verifier = secrets.token_urlsafe(64)
        
        # Generate code challenge (S256)
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        
        return code_verifier, code_challenge
    
    def _resolve_scopes(
        self, 
        provider: str, 
        services: Optional[List[str]] = None,
        custom_scopes: Optional[List[str]] = None,
    ) -> List[str]:
        """Resolve scope names to actual OAuth scopes."""
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        
        config = OAUTH_PROVIDERS[provider]
        all_scopes = set()
        
        # Add scopes for requested services
        if services:
            for service in services:
                if service in config.scopes:
                    all_scopes.update(config.scopes[service])
        else:
            # Default to "all" if available
            if "all" in config.scopes:
                all_scopes.update(config.scopes["all"])
        
        # Add custom scopes
        if custom_scopes:
            all_scopes.update(custom_scopes)
        
        return list(all_scopes)
    
    def get_supported_providers(self) -> List[str]:
        """Get list of supported OAuth providers."""
        return list(OAUTH_PROVIDERS.keys())
    
    def get_provider_info(self, provider: str) -> Dict[str, Any]:
        """Get information about an OAuth provider."""
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        
        config = OAUTH_PROVIDERS[provider]
        return {
            "name": config.name,
            "services": list(config.scopes.keys()),
            "supports_pkce": config.supports_pkce,
        }
    
    def get_auth_url(
        self,
        provider: str,
        client_id: str,
        client_secret: Optional[str] = None,
        services: Optional[List[str]] = None,
        scopes: Optional[List[str]] = None,
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
    ) -> str:
        """
        Generate OAuth authorization URL.
        
        Args:
            provider: OAuth provider (google, microsoft, etc.)
            client_id: OAuth client ID
            client_secret: OAuth client secret (some providers need this for token exchange)
            services: Service names to request scopes for (gmail, calendar, etc.)
            scopes: Custom scopes to add
            redirect_uri: Custom redirect URI
            state: Custom state parameter (generated if not provided)
        
        Returns:
            Authorization URL to redirect user to
        """
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        
        config = OAUTH_PROVIDERS[provider]
        
        # Resolve scopes
        resolved_scopes = self._resolve_scopes(provider, services, scopes)
        if not resolved_scopes:
            raise ValueError(f"No scopes specified for provider {provider}")
        
        # Generate state token
        if state is None:
            state = secrets.token_urlsafe(32)
        
        # Generate PKCE if supported
        code_verifier = None
        code_challenge = None
        if config.supports_pkce:
            code_verifier, code_challenge = self._generate_pkce()
        
        # Use provided or default redirect URI
        redirect = redirect_uri or self._redirect_uri
        
        # Build authorization URL parameters
        params = {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": " ".join(resolved_scopes),
            "state": state,
        }
        
        # Add PKCE challenge if supported
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        
        # Add provider-specific parameters
        params.update(config.extra_auth_params)
        
        # Store pending auth
        pending = PendingAuth(
            state=state,
            provider=provider,
            services=services or [],
            scopes=resolved_scopes,
            redirect_uri=redirect,
            code_verifier=code_verifier,
            created_at=datetime.utcnow(),
            client_id=client_id,
            client_secret=client_secret,
        )
        self._pending[state] = pending
        self._save_pending_states()
        
        # Build URL
        url = f"{config.auth_url}?{urlencode(params)}"
        logger.info(f"Generated OAuth URL for {provider}: {url[:100]}...")
        
        return url
    
    async def handle_callback(
        self,
        code: str,
        state: str,
    ) -> Dict[str, Any]:
        """
        Handle OAuth callback and exchange code for tokens.
        
        Args:
            code: Authorization code from callback
            state: State parameter for CSRF verification
        
        Returns:
            Dict with provider, services, and success status
        """
        if not HAS_HTTPX:
            raise ImportError(
                "httpx library required for OAuth flows. "
                "Run: pip install httpx"
            )
        
        # Verify state
        if state not in self._pending:
            raise ValueError("Invalid or expired state parameter")
        
        pending = self._pending[state]
        
        if pending.is_expired():
            del self._pending[state]
            self._save_pending_states()
            raise ValueError("Authorization request expired")
        
        config = OAUTH_PROVIDERS[pending.provider]
        
        # Build token request
        token_data = {
            "client_id": pending.client_id,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": pending.redirect_uri,
        }
        
        # Add client secret if provided
        if pending.client_secret:
            token_data["client_secret"] = pending.client_secret
        
        # Add PKCE verifier if used
        if pending.code_verifier:
            token_data["code_verifier"] = pending.code_verifier
        
        # Add provider-specific token params
        token_data.update(config.extra_token_params)
        
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.token_url,
                data=token_data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.text}")
                raise ValueError(f"Token exchange failed: {response.status_code}")
            
            tokens = response.json()
        
        # Store tokens in credential store
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_in = tokens.get("expires_in", 3600)
        
        if not access_token:
            raise ValueError("No access token in response")
        
        # Save to credential store
        self._credential_store.save_token(
            provider=pending.provider,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            scopes=pending.scopes,
            extra_data={
                "services": pending.services,
                "token_type": tokens.get("token_type", "Bearer"),
            },
        )
        
        # Also save client credentials for refresh flows
        if pending.client_secret:
            self._credential_store.save_client_credentials(
                provider=pending.provider,
                client_id=pending.client_id,
                client_secret=pending.client_secret,
            )
        
        # Clean up pending state
        del self._pending[state]
        self._save_pending_states()
        
        logger.info(f"Successfully authenticated {pending.provider}")
        
        return {
            "provider": pending.provider,
            "services": pending.services,
            "scopes": pending.scopes,
            "success": True,
        }
    
    async def refresh_token(self, provider: str) -> bool:
        """
        Refresh expired access token using refresh token.
        
        Args:
            provider: Provider to refresh token for
        
        Returns:
            True if refresh successful
        """
        if not HAS_HTTPX:
            raise ImportError("httpx library required")
        
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        
        # Get stored credentials
        cred = self._credential_store.get(provider)
        if not cred or not cred.data.get("refresh_token"):
            raise ValueError(f"No refresh token for {provider}")
        
        # Get client credentials
        client_creds = self._credential_store.get_client_credentials(provider)
        if not client_creds:
            raise ValueError(f"No client credentials for {provider}")
        
        config = OAUTH_PROVIDERS[provider]
        
        # Build refresh request
        refresh_data = {
            "client_id": client_creds["client_id"],
            "client_secret": client_creds.get("client_secret"),
            "refresh_token": cred.data["refresh_token"],
            "grant_type": "refresh_token",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                config.token_url,
                data=refresh_data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            
            if response.status_code != 200:
                logger.error(f"Token refresh failed: {response.text}")
                return False
            
            tokens = response.json()
        
        # Update stored tokens
        self._credential_store.save_token(
            provider=provider,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token", cred.data.get("refresh_token")),
            expires_in=tokens.get("expires_in", 3600),
            scopes=cred.scopes,
            extra_data=cred.data.get("extra_data", {}),
        )
        
        logger.info(f"Refreshed token for {provider}")
        return True
    
    def is_connected(self, provider: str) -> bool:
        """Check if a provider is connected with valid tokens."""
        return self._credential_store.has_valid(provider)
    
    def get_connection_status(self) -> Dict[str, Dict[str, Any]]:
        """Get connection status for all providers."""
        status = {}
        
        for provider in OAUTH_PROVIDERS:
            cred = self._credential_store.get(provider)
            if cred:
                status[provider] = {
                    "connected": not cred.is_expired(),
                    "scopes": cred.scopes,
                    "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
                    "has_refresh_token": bool(cred.data.get("refresh_token")),
                }
            else:
                status[provider] = {
                    "connected": False,
                    "scopes": [],
                    "expires_at": None,
                    "has_refresh_token": False,
                }
        
        return status
    
    def disconnect(self, provider: str) -> bool:
        """Disconnect a provider by removing stored credentials."""
        success = self._credential_store.delete(provider)
        if success:
            # Also remove client credentials
            self._credential_store._backend.delete(f"{provider}:client")
            logger.info(f"Disconnected {provider}")
        return success


# ============================================================
#  SINGLETON ACCESS
# ============================================================

_oauth_flow: Optional[OAuthFlow] = None


def get_oauth_flow() -> OAuthFlow:
    """Get singleton OAuthFlow instance."""
    global _oauth_flow
    if _oauth_flow is None:
        _oauth_flow = OAuthFlow()
    return _oauth_flow


def reset_oauth_flow():
    """Reset the singleton (for testing)."""
    global _oauth_flow
    _oauth_flow = None
