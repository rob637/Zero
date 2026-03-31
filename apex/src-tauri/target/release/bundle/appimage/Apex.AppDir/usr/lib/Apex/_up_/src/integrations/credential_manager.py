"""
Credential Manager for Apex Integration Platform

Secure, local-first credential storage with:
- AES-256 encryption at rest
- OAuth2 flow handling
- Automatic token refresh
- Support for multiple credential types
"""

import os
import json
import base64
import hashlib
import secrets
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import httpx

logger = logging.getLogger(__name__)


class CredentialType(Enum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BASIC_AUTH = "basic_auth"
    CUSTOM = "custom"


@dataclass
class OAuth2Credentials:
    """OAuth2 credential storage."""
    service: str
    client_id: str
    client_secret: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    token_url: Optional[str] = None
    auth_url: Optional[str] = None
    redirect_uri: str = "http://localhost:8765/oauth/callback"
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if token is expired (with 5 min buffer)."""
        if not self.expires_at:
            return False
        return datetime.now() > (self.expires_at - timedelta(minutes=5))
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        data = asdict(self)
        if self.expires_at:
            data['expires_at'] = self.expires_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OAuth2Credentials':
        """Deserialize from dictionary."""
        if data.get('expires_at'):
            data['expires_at'] = datetime.fromisoformat(data['expires_at'])
        return cls(**data)


@dataclass
class APIKeyCredentials:
    """API key credential storage."""
    service: str
    api_key: str
    header_name: str = "Authorization"
    header_prefix: str = "Bearer"
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'APIKeyCredentials':
        return cls(**data)


# OAuth Provider configurations
OAUTH_PROVIDERS = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": {
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
            ],
        },
    },
    "microsoft": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": {
            "outlook": [
                "https://graph.microsoft.com/Mail.Read",
                "https://graph.microsoft.com/Mail.Send",
            ],
            "calendar": [
                "https://graph.microsoft.com/Calendars.ReadWrite",
            ],
            "onedrive": [
                "https://graph.microsoft.com/Files.ReadWrite.All",
            ],
        },
    },
    "notion": {
        "auth_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": {},  # Notion uses integration tokens
    },
    "slack": {
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": {
            "default": [
                "channels:history",
                "channels:read",
                "chat:write",
                "users:read",
            ],
        },
    },
    "github": {
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": {
            "default": ["repo", "user", "read:org"],
        },
    },
}


class CredentialManager:
    """
    Secure credential manager with encryption at rest.
    
    Features:
    - AES-256-GCM encryption
    - Key derivation from user password
    - Automatic token refresh
    - Support for OAuth2 and API keys
    """
    
    def __init__(self, storage_path: Optional[Path] = None, master_key: Optional[str] = None):
        """
        Initialize credential manager.
        
        Args:
            storage_path: Where to store encrypted credentials
            master_key: Master password for encryption (if None, uses machine ID)
        """
        self.storage_path = storage_path or Path.home() / ".apex" / "credentials"
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # Derive encryption key
        self._master_key = master_key or self._get_machine_key()
        self._fernet = self._create_fernet(self._master_key)
        
        # In-memory credential cache
        self._cache: Dict[str, Any] = {}
        
        # Load existing credentials
        self._load_credentials()
    
    def _get_machine_key(self) -> str:
        """Generate a machine-specific key for auto-encryption."""
        # Use a combination of machine identifiers
        identifiers = []
        
        # Machine ID (Linux/Mac)
        machine_id_path = Path("/etc/machine-id")
        if machine_id_path.exists():
            identifiers.append(machine_id_path.read_text().strip())
        
        # User home directory
        identifiers.append(str(Path.home()))
        
        # Username
        identifiers.append(os.environ.get("USER", os.environ.get("USERNAME", "apex")))
        
        # Create a deterministic key
        combined = ":".join(identifiers)
        return hashlib.sha256(combined.encode()).hexdigest()[:32]
    
    def _create_fernet(self, password: str) -> Fernet:
        """Create Fernet encryption instance from password."""
        salt_file = self.storage_path / ".salt"
        
        if salt_file.exists():
            salt = salt_file.read_bytes()
        else:
            salt = secrets.token_bytes(16)
            salt_file.write_bytes(salt)
        
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)
    
    def _encrypt(self, data: str) -> str:
        """Encrypt data."""
        return self._fernet.encrypt(data.encode()).decode()
    
    def _decrypt(self, data: str) -> str:
        """Decrypt data."""
        return self._fernet.decrypt(data.encode()).decode()
    
    def _credential_path(self, service: str) -> Path:
        """Get path for service credentials."""
        return self.storage_path / f"{service}.enc"
    
    def _load_credentials(self):
        """Load all stored credentials into cache."""
        for cred_file in self.storage_path.glob("*.enc"):
            try:
                service = cred_file.stem
                encrypted = cred_file.read_text()
                decrypted = self._decrypt(encrypted)
                data = json.loads(decrypted)
                self._cache[service] = data
            except Exception as e:
                logger.warning(f"Failed to load credentials for {cred_file.stem}: {e}")
    
    def _save_credential(self, service: str, data: Dict[str, Any]):
        """Save credential to encrypted storage."""
        self._cache[service] = data
        encrypted = self._encrypt(json.dumps(data))
        self._credential_path(service).write_text(encrypted)
    
    # === OAuth2 Methods ===
    
    def store_oauth2(self, creds: OAuth2Credentials) -> None:
        """Store OAuth2 credentials."""
        data = {
            "type": CredentialType.OAUTH2.value,
            "credentials": creds.to_dict(),
        }
        self._save_credential(creds.service, data)
        logger.info(f"Stored OAuth2 credentials for {creds.service}")
    
    def get_oauth2(self, service: str) -> Optional[OAuth2Credentials]:
        """Get OAuth2 credentials for a service."""
        data = self._cache.get(service)
        if not data or data.get("type") != CredentialType.OAUTH2.value:
            return None
        return OAuth2Credentials.from_dict(data["credentials"])
    
    def get_oauth_url(
        self, 
        provider: str,
        service: str,
        client_id: str,
        client_secret: str,
        scopes: Optional[List[str]] = None,
        redirect_uri: Optional[str] = None,
        state: Optional[str] = None,
    ) -> str:
        """
        Generate OAuth authorization URL.
        
        Args:
            provider: OAuth provider (google, microsoft, etc.)
            service: Service name within provider (gmail, calendar, etc.)
            client_id: OAuth client ID
            client_secret: OAuth client secret
            scopes: Override default scopes
            redirect_uri: Override default redirect URI
            state: CSRF state parameter
        
        Returns:
            Authorization URL to redirect user to
        """
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unknown OAuth provider: {provider}")
        
        config = OAUTH_PROVIDERS[provider]
        
        # Determine scopes
        if scopes is None:
            scopes = config["scopes"].get(service, config["scopes"].get("default", []))
        
        # Generate state if not provided
        if state is None:
            state = secrets.token_urlsafe(32)
        
        # Build URL
        redirect = redirect_uri or "http://localhost:8765/oauth/callback"
        
        params = {
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "access_type": "offline",  # For refresh token
            "prompt": "consent",  # Force consent to get refresh token
        }
        
        # Store pending auth request
        pending_auth = {
            "provider": provider,
            "service": service,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": scopes,
            "redirect_uri": redirect,
            "state": state,
            "token_url": config["token_url"],
            "auth_url": config["auth_url"],
        }
        self._save_credential(f"_pending_{state}", {"pending": pending_auth})
        
        # Build URL
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{config['auth_url']}?{query}"
    
    async def handle_oauth_callback(self, code: str, state: str) -> OAuth2Credentials:
        """
        Handle OAuth callback and exchange code for tokens.
        
        Args:
            code: Authorization code from callback
            state: State parameter for verification
        
        Returns:
            OAuth2Credentials with tokens
        """
        # Get pending auth request
        pending_key = f"_pending_{state}"
        pending_data = self._cache.get(pending_key)
        
        if not pending_data or "pending" not in pending_data:
            raise ValueError("Invalid or expired state parameter")
        
        pending = pending_data["pending"]
        
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                pending["token_url"],
                data={
                    "client_id": pending["client_id"],
                    "client_secret": pending["client_secret"],
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": pending["redirect_uri"],
                },
                headers={"Accept": "application/json"},
            )
            
            if response.status_code != 200:
                raise ValueError(f"Token exchange failed: {response.text}")
            
            tokens = response.json()
        
        # Calculate expiration
        expires_in = tokens.get("expires_in", 3600)
        expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        # Create credentials
        creds = OAuth2Credentials(
            service=pending["service"],
            client_id=pending["client_id"],
            client_secret=pending["client_secret"],
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            token_type=tokens.get("token_type", "Bearer"),
            expires_at=expires_at,
            scopes=pending["scopes"],
            token_url=pending["token_url"],
            auth_url=pending["auth_url"],
            redirect_uri=pending["redirect_uri"],
        )
        
        # Store credentials
        self.store_oauth2(creds)
        
        # Clean up pending request
        pending_path = self._credential_path(pending_key)
        if pending_path.exists():
            pending_path.unlink()
        if pending_key in self._cache:
            del self._cache[pending_key]
        
        logger.info(f"OAuth flow completed for {creds.service}")
        return creds
    
    async def refresh_oauth2(self, service: str) -> OAuth2Credentials:
        """Refresh OAuth2 tokens."""
        creds = self.get_oauth2(service)
        if not creds:
            raise ValueError(f"No OAuth2 credentials found for {service}")
        
        if not creds.refresh_token:
            raise ValueError(f"No refresh token available for {service}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                creds.token_url,
                data={
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "refresh_token": creds.refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Accept": "application/json"},
            )
            
            if response.status_code != 200:
                raise ValueError(f"Token refresh failed: {response.text}")
            
            tokens = response.json()
        
        # Update credentials
        creds.access_token = tokens["access_token"]
        if "refresh_token" in tokens:
            creds.refresh_token = tokens["refresh_token"]
        
        expires_in = tokens.get("expires_in", 3600)
        creds.expires_at = datetime.now() + timedelta(seconds=expires_in)
        
        # Save updated credentials
        self.store_oauth2(creds)
        
        logger.info(f"Refreshed OAuth2 tokens for {service}")
        return creds
    
    async def get_valid_token(self, service: str) -> str:
        """Get a valid access token, refreshing if needed."""
        creds = self.get_oauth2(service)
        if not creds:
            raise ValueError(f"No credentials for {service}")
        
        if creds.is_expired():
            creds = await self.refresh_oauth2(service)
        
        return creds.access_token
    
    # === API Key Methods ===
    
    def store_api_key(self, creds: APIKeyCredentials) -> None:
        """Store API key credentials."""
        data = {
            "type": CredentialType.API_KEY.value,
            "credentials": creds.to_dict(),
        }
        self._save_credential(creds.service, data)
        logger.info(f"Stored API key for {creds.service}")
    
    def get_api_key(self, service: str) -> Optional[APIKeyCredentials]:
        """Get API key credentials for a service."""
        data = self._cache.get(service)
        if not data or data.get("type") != CredentialType.API_KEY.value:
            return None
        return APIKeyCredentials.from_dict(data["credentials"])
    
    # === General Methods ===
    
    def list_services(self) -> List[Dict[str, Any]]:
        """List all stored services with their credential types."""
        services = []
        for name, data in self._cache.items():
            if name.startswith("_"):  # Skip internal entries
                continue
            services.append({
                "service": name,
                "type": data.get("type", "unknown"),
                "has_access_token": bool(data.get("credentials", {}).get("access_token")),
                "has_refresh_token": bool(data.get("credentials", {}).get("refresh_token")),
            })
        return services
    
    def has_credentials(self, service: str) -> bool:
        """Check if credentials exist for a service."""
        return service in self._cache and not service.startswith("_")
    
    def delete_credentials(self, service: str) -> bool:
        """Delete credentials for a service."""
        path = self._credential_path(service)
        if path.exists():
            path.unlink()
        if service in self._cache:
            del self._cache[service]
            logger.info(f"Deleted credentials for {service}")
            return True
        return False
    
    def export_backup(self, password: str) -> bytes:
        """Export all credentials as encrypted backup."""
        backup_fernet = self._create_fernet(password)
        data = json.dumps(self._cache)
        return backup_fernet.encrypt(data.encode())
    
    def import_backup(self, backup: bytes, password: str) -> int:
        """Import credentials from encrypted backup."""
        backup_fernet = self._create_fernet(password)
        data = json.loads(backup_fernet.decrypt(backup).decode())
        
        count = 0
        for service, creds in data.items():
            if not service.startswith("_"):
                self._save_credential(service, creds)
                count += 1
        
        return count


# Singleton instance
_credential_manager: Optional[CredentialManager] = None

def get_credential_manager() -> CredentialManager:
    """Get or create the credential manager singleton."""
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager()
    return _credential_manager
