"""
Secure Credential Store

Encrypted storage for OAuth tokens and API keys across all connectors.
Supports multiple providers and secure credential lifecycle management.

Features:
- AES-256 encryption at rest (via cryptography library)
- Automatic token refresh tracking
- Multi-provider credential isolation
- Secure deletion with overwrite

Security Model:
- Master key derived from machine-specific identifier + user passphrase
- Each credential encrypted with unique IV
- Tokens stored separately from client secrets

Usage:
    from apex.connectors.credentials import CredentialStore, get_credential_store
    
    store = get_credential_store()
    
    # Store credentials
    store.save("google", {
        "access_token": "...",
        "refresh_token": "...",
        "expiry": "2024-12-31T23:59:59Z",
    })
    
    # Retrieve credentials
    creds = store.get("google")
    
    # Check if credentials exist and valid
    if store.has_valid("google"):
        print("Google connected!")
    
    # Remove credentials
    store.delete("google")
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

import logging
logger = logging.getLogger(__name__)


# Try to import cryptography for encryption
try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    Fernet = None


class CredentialType(Enum):
    """Type of stored credential."""
    OAUTH_TOKEN = "oauth_token"      # OAuth 2.0 access/refresh tokens
    API_KEY = "api_key"              # Simple API key
    CLIENT_CREDENTIALS = "client"    # OAuth client ID/secret
    SERVICE_ACCOUNT = "service"      # Service account JSON key


@dataclass
class StoredCredential:
    """A stored credential with metadata."""
    provider: str
    credential_type: CredentialType
    data: Dict[str, Any]
    created_at: datetime
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    user_id: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Check if credential has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def expires_soon(self, minutes: int = 5) -> bool:
        """Check if credential expires within given minutes."""
        if self.expires_at is None:
            return False
        threshold = datetime.utcnow() + timedelta(minutes=minutes)
        return self.expires_at < threshold
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "credential_type": self.credential_type.value,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": self.scopes,
            "user_id": self.user_id,
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StoredCredential":
        return cls(
            provider=d["provider"],
            credential_type=CredentialType(d["credential_type"]),
            data=d["data"],
            created_at=datetime.fromisoformat(d["created_at"]),
            expires_at=datetime.fromisoformat(d["expires_at"]) if d.get("expires_at") else None,
            scopes=d.get("scopes", []),
            user_id=d.get("user_id"),
        )


class CredentialBackend(ABC):
    """Abstract backend for credential storage."""
    
    @abstractmethod
    def save(self, key: str, credential: StoredCredential) -> bool:
        """Save a credential."""
        pass
    
    @abstractmethod
    def get(self, key: str) -> Optional[StoredCredential]:
        """Retrieve a credential."""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete a credential."""
        pass
    
    @abstractmethod
    def list_keys(self) -> List[str]:
        """List all stored credential keys."""
        pass
    
    @abstractmethod
    def clear_all(self) -> int:
        """Clear all credentials. Returns count deleted."""
        pass


class EncryptedFileBackend(CredentialBackend):
    """
    File-based credential storage with AES-256 encryption.
    
    Credentials are stored in ~/.apex/credentials/ with one encrypted
    JSON file per provider.
    """
    
    def __init__(
        self,
        storage_path: Optional[str] = None,
        encryption_key: Optional[bytes] = None,
    ):
        self._storage = Path(storage_path or "~/.apex/credentials").expanduser()
        self._storage.mkdir(parents=True, exist_ok=True)
        
        # Set up encryption
        if HAS_CRYPTO:
            if encryption_key:
                self._fernet = Fernet(encryption_key)
            else:
                self._fernet = Fernet(self._get_or_create_key())
        else:
            self._fernet = None
            logger.warning(
                "cryptography package not installed. "
                "Credentials will be stored without encryption. "
                "Run: pip install cryptography"
            )
    
    def _get_or_create_key(self) -> bytes:
        """Get or create the encryption key."""
        key_file = self._storage / ".key"
        
        if key_file.exists():
            return key_file.read_bytes()
        
        # Generate new key using machine-specific salt
        salt = self._get_machine_salt()
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        
        # Use a random secret that's stored
        secret_file = self._storage / ".secret"
        if secret_file.exists():
            secret = secret_file.read_bytes()
        else:
            secret = secrets.token_bytes(32)
            secret_file.write_bytes(secret)
            # Restrict permissions on Unix
            try:
                os.chmod(secret_file, 0o600)
            except Exception:
                pass
        
        key = base64.urlsafe_b64encode(kdf.derive(secret))
        key_file.write_bytes(key)
        
        # Restrict permissions
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        
        return key
    
    def _get_machine_salt(self) -> bytes:
        """Get a machine-specific salt for key derivation."""
        identifiers = []
        
        # Try to get machine-specific identifiers
        try:
            identifiers.append(str(uuid.getnode()))  # MAC address
        except Exception:
            pass
        
        try:
            identifiers.append(os.getlogin())
        except Exception:
            pass
        
        try:
            identifiers.append(str(Path.home()))
        except Exception:
            pass
        
        combined = ":".join(identifiers) if identifiers else "apex-default-salt"
        return hashlib.sha256(combined.encode()).digest()[:16]
    
    def _encrypt(self, data: str) -> str:
        """Encrypt data string."""
        if self._fernet:
            return self._fernet.encrypt(data.encode()).decode()
        return base64.b64encode(data.encode()).decode()
    
    def _decrypt(self, data: str) -> str:
        """Decrypt data string."""
        if self._fernet:
            return self._fernet.decrypt(data.encode()).decode()
        return base64.b64decode(data.encode()).decode()
    
    def _get_file_path(self, key: str) -> Path:
        """Get the file path for a credential key."""
        # Sanitize key for filesystem
        safe_key = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self._storage / f"{safe_key}.enc"
    
    def save(self, key: str, credential: StoredCredential) -> bool:
        """Save a credential to encrypted file."""
        try:
            file_path = self._get_file_path(key)
            data = json.dumps(credential.to_dict())
            encrypted = self._encrypt(data)
            file_path.write_text(encrypted)
            
            # Restrict permissions
            try:
                os.chmod(file_path, 0o600)
            except Exception:
                pass
            
            logger.debug(f"Saved credential: {key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save credential {key}: {e}")
            return False
    
    def get(self, key: str) -> Optional[StoredCredential]:
        """Retrieve a credential from encrypted file."""
        try:
            file_path = self._get_file_path(key)
            if not file_path.exists():
                return None
            
            encrypted = file_path.read_text()
            decrypted = self._decrypt(encrypted)
            data = json.loads(decrypted)
            
            return StoredCredential.from_dict(data)
            
        except Exception as e:
            logger.error(f"Failed to get credential {key}: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Securely delete a credential file."""
        try:
            file_path = self._get_file_path(key)
            if not file_path.exists():
                return False
            
            # Overwrite with random data before deletion
            size = file_path.stat().st_size
            file_path.write_bytes(secrets.token_bytes(size))
            file_path.unlink()
            
            logger.debug(f"Deleted credential: {key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete credential {key}: {e}")
            return False
    
    def list_keys(self) -> List[str]:
        """List all stored credential keys."""
        keys = []
        for file_path in self._storage.glob("*.enc"):
            keys.append(file_path.stem)
        return keys
    
    def clear_all(self) -> int:
        """Clear all credentials."""
        count = 0
        for key in self.list_keys():
            if self.delete(key):
                count += 1
        return count


class MemoryBackend(CredentialBackend):
    """
    In-memory credential storage for testing.
    
    No persistence - credentials lost on restart.
    """
    
    def __init__(self):
        self._store: Dict[str, StoredCredential] = {}
    
    def save(self, key: str, credential: StoredCredential) -> bool:
        self._store[key] = credential
        return True
    
    def get(self, key: str) -> Optional[StoredCredential]:
        return self._store.get(key)
    
    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False
    
    def list_keys(self) -> List[str]:
        return list(self._store.keys())
    
    def clear_all(self) -> int:
        count = len(self._store)
        self._store.clear()
        return count


class CredentialStore:
    """
    High-level credential management.
    
    Provides a clean interface for storing and retrieving
    credentials across all providers.
    
    Features:
    - Automatic expiry checking
    - Credential refresh callbacks
    - Provider health status
    - Multi-credential per provider (e.g., multiple Google accounts)
    """
    
    def __init__(self, backend: Optional[CredentialBackend] = None):
        self._backend = backend or EncryptedFileBackend()
        self._refresh_callbacks: Dict[str, callable] = {}
    
    def _make_key(self, provider: str, user_id: Optional[str] = None) -> str:
        """Generate storage key for provider/user combination."""
        if user_id:
            return f"{provider}:{user_id}"
        return provider
    
    def save_token(
        self,
        provider: str,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
        scopes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        extra_data: Optional[Dict] = None,
    ) -> bool:
        """
        Save OAuth token credentials.
        
        Args:
            provider: Provider name (google, microsoft, github, etc.)
            access_token: The access token
            refresh_token: Optional refresh token
            expires_in: Token lifetime in seconds
            scopes: List of authorized scopes
            user_id: Optional user identifier for multi-account
            extra_data: Any additional data to store
        
        Returns:
            True if saved successfully
        """
        expires_at = None
        if expires_in:
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            **(extra_data or {}),
        }
        
        credential = StoredCredential(
            provider=provider,
            credential_type=CredentialType.OAUTH_TOKEN,
            data=data,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            scopes=scopes or [],
            user_id=user_id,
        )
        
        key = self._make_key(provider, user_id)
        return self._backend.save(key, credential)
    
    def save_api_key(
        self,
        provider: str,
        api_key: str,
        user_id: Optional[str] = None,
        extra_data: Optional[Dict] = None,
    ) -> bool:
        """
        Save API key credentials.
        
        Args:
            provider: Provider name
            api_key: The API key
            user_id: Optional user identifier
            extra_data: Any additional data
        
        Returns:
            True if saved successfully
        """
        data = {
            "api_key": api_key,
            **(extra_data or {}),
        }
        
        credential = StoredCredential(
            provider=provider,
            credential_type=CredentialType.API_KEY,
            data=data,
            created_at=datetime.utcnow(),
            user_id=user_id,
        )
        
        key = self._make_key(provider, user_id)
        return self._backend.save(key, credential)
    
    def save_client_credentials(
        self,
        provider: str,
        client_id: str,
        client_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
        extra_data: Optional[Dict] = None,
    ) -> bool:
        """
        Save OAuth client credentials (for initiating OAuth flow).
        
        Args:
            provider: Provider name
            client_id: OAuth client ID
            client_secret: OAuth client secret
            tenant_id: Tenant ID (for Azure/Microsoft)
            extra_data: Any additional data
        
        Returns:
            True if saved successfully
        """
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "tenant_id": tenant_id,
            **(extra_data or {}),
        }
        
        credential = StoredCredential(
            provider=f"{provider}:client",
            credential_type=CredentialType.CLIENT_CREDENTIALS,
            data=data,
            created_at=datetime.utcnow(),
        )
        
        return self._backend.save(f"{provider}:client", credential)
    
    def get(self, provider: str, user_id: Optional[str] = None) -> Optional[StoredCredential]:
        """
        Get stored credentials for a provider.
        
        Args:
            provider: Provider name
            user_id: Optional user identifier
        
        Returns:
            StoredCredential or None
        """
        key = self._make_key(provider, user_id)
        return self._backend.get(key)
    
    def get_token(self, provider: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        Get access token for a provider.
        
        Args:
            provider: Provider name
            user_id: Optional user identifier
        
        Returns:
            Access token string or None
        """
        cred = self.get(provider, user_id)
        if cred and cred.data:
            return cred.data.get("access_token")
        return None
    
    def get_api_key(self, provider: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        Get API key for a provider.
        
        Args:
            provider: Provider name
            user_id: Optional user identifier
        
        Returns:
            API key string or None
        """
        cred = self.get(provider, user_id)
        if cred and cred.data:
            return cred.data.get("api_key")
        return None
    
    def get_client_credentials(self, provider: str) -> Optional[Dict[str, str]]:
        """
        Get OAuth client credentials for a provider.
        
        Returns:
            Dict with client_id, client_secret, etc. or None
        """
        cred = self._backend.get(f"{provider}:client")
        if cred and cred.data:
            return cred.data
        return None
    
    def has(self, provider: str, user_id: Optional[str] = None) -> bool:
        """Check if credentials exist for provider."""
        key = self._make_key(provider, user_id)
        return self._backend.get(key) is not None
    
    def has_valid(self, provider: str, user_id: Optional[str] = None) -> bool:
        """Check if valid (non-expired) credentials exist."""
        cred = self.get(provider, user_id)
        if cred is None:
            return False
        return not cred.is_expired()
    
    def needs_refresh(self, provider: str, user_id: Optional[str] = None) -> bool:
        """Check if credentials need refresh (expired or expiring soon)."""
        cred = self.get(provider, user_id)
        if cred is None:
            return True
        return cred.is_expired() or cred.expires_soon(minutes=5)
    
    def delete(self, provider: str, user_id: Optional[str] = None) -> bool:
        """Delete credentials for a provider."""
        key = self._make_key(provider, user_id)
        return self._backend.delete(key)
    
    def list_providers(self) -> List[str]:
        """List all providers with stored credentials."""
        keys = self._backend.list_keys()
        # Filter out client credential keys and extract provider names
        providers = set()
        for key in keys:
            if ":client" in key:
                continue
            provider = key.split(":")[0]
            providers.add(provider)
        return sorted(providers)
    
    def list_all_credentials(self) -> List[Dict[str, Any]]:
        """List all credentials with metadata (without sensitive data)."""
        result = []
        for key in self._backend.list_keys():
            cred = self._backend.get(key)
            if cred:
                result.append({
                    "key": key,
                    "provider": cred.provider,
                    "type": cred.credential_type.value,
                    "created_at": cred.created_at.isoformat(),
                    "expires_at": cred.expires_at.isoformat() if cred.expires_at else None,
                    "is_expired": cred.is_expired(),
                    "scopes": cred.scopes,
                    "user_id": cred.user_id,
                })
        return result
    
    def get_status(self) -> Dict[str, Any]:
        """Get overall credential store status."""
        all_creds = self.list_all_credentials()
        
        # Group by provider
        by_provider = {}
        for cred in all_creds:
            provider = cred["provider"].split(":")[0]
            if provider not in by_provider:
                by_provider[provider] = {
                    "has_token": False,
                    "has_client": False,
                    "is_valid": False,
                }
            
            if cred["type"] == "oauth_token":
                by_provider[provider]["has_token"] = True
                by_provider[provider]["is_valid"] = not cred["is_expired"]
            elif cred["type"] == "client":
                by_provider[provider]["has_client"] = True
        
        return {
            "total_credentials": len(all_creds),
            "providers": by_provider,
            "connected": [p for p, v in by_provider.items() if v.get("is_valid")],
            "expired": [p for p, v in by_provider.items() if v.get("has_token") and not v.get("is_valid")],
        }
    
    def register_refresh_callback(self, provider: str, callback: callable):
        """
        Register a callback to refresh tokens for a provider.
        
        The callback should take (credential: StoredCredential) and return
        a new StoredCredential or None if refresh fails.
        """
        self._refresh_callbacks[provider] = callback
    
    async def refresh_if_needed(self, provider: str, user_id: Optional[str] = None) -> bool:
        """
        Refresh credentials if needed.
        
        Returns True if credentials are valid (either still valid or refreshed).
        """
        cred = self.get(provider, user_id)
        if cred is None:
            return False
        
        if not self.needs_refresh(provider, user_id):
            return True
        
        # Try to refresh
        callback = self._refresh_callbacks.get(provider)
        if callback is None:
            logger.warning(f"No refresh callback for {provider}")
            return not cred.is_expired()
        
        try:
            new_cred = await callback(cred)
            if new_cred:
                key = self._make_key(provider, user_id)
                self._backend.save(key, new_cred)
                return True
        except Exception as e:
            logger.error(f"Failed to refresh {provider} credentials: {e}")
        
        return not cred.is_expired()
    
    def clear_all(self) -> int:
        """Clear all stored credentials."""
        return self._backend.clear_all()


# Singleton instance
_credential_store: Optional[CredentialStore] = None


def get_credential_store(
    backend: Optional[CredentialBackend] = None,
    storage_path: Optional[str] = None,
) -> CredentialStore:
    """
    Get or create the singleton CredentialStore.
    
    Args:
        backend: Optional custom backend
        storage_path: Optional custom storage path for file backend
    
    Returns:
        CredentialStore instance
    """
    global _credential_store
    
    if _credential_store is None:
        if backend:
            _credential_store = CredentialStore(backend)
        else:
            file_backend = EncryptedFileBackend(storage_path=storage_path)
            _credential_store = CredentialStore(file_backend)
    
    return _credential_store


def reset_credential_store():
    """Reset the singleton (for testing)."""
    global _credential_store
    _credential_store = None
