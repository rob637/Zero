"""
OAuth Broker Client

Connects local Ziggy to the central OAuth broker for one-click authentication.

This client:
1. Redirects users to the cloud broker for OAuth
2. Receives tokens back via callback
3. Stores tokens locally
4. Handles token refresh via the broker

Usage:
    from connectors.broker_client import BrokerClient, get_broker_client
    
    client = get_broker_client()
    
    # Start OAuth flow
    auth_url = client.get_auth_url("google")
    # Redirect user to auth_url
    
    # Handle callback (tokens come back)
    tokens = client.parse_callback(request_url)
    
    # Refresh token
    new_tokens = await client.refresh_token("google", refresh_token)
"""

import os
import json
import base64
import logging
from typing import Optional, Dict, Any, List
from urllib.parse import urlencode, urlparse, parse_qs
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Cloud broker URL (production)
DEFAULT_BROKER_URL = "https://auth.ziggy.ai"

# For development, can use local broker
DEV_BROKER_URL = "http://localhost:8080"

# Callback URL for local Ziggy
LOCAL_CALLBACK = "http://127.0.0.1:8000/oauth/callback"


@dataclass
class BrokerConfig:
    """Configuration for the broker client."""
    broker_url: str = DEFAULT_BROKER_URL
    local_callback: str = LOCAL_CALLBACK
    use_cloud: bool = True  # If False, use self-hosted credentials
    
    @classmethod
    def from_env(cls) -> "BrokerConfig":
        """Load config from environment."""
        return cls(
            broker_url=os.environ.get("ZIGGY_BROKER_URL", DEFAULT_BROKER_URL),
            local_callback=os.environ.get("ZIGGY_CALLBACK_URL", LOCAL_CALLBACK),
            use_cloud=os.environ.get("ZIGGY_USE_CLOUD", "true").lower() == "true",
        )


@dataclass
class TokenSet:
    """OAuth tokens for a provider."""
    provider: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    token_type: str = "Bearer"
    
    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        return datetime.now() >= self.expires_at
    
    @property
    def needs_refresh(self) -> bool:
        if not self.expires_at:
            return False
        buffer = timedelta(minutes=5)
        return datetime.now() >= (self.expires_at - buffer)
    
    def to_dict(self) -> Dict:
        return {
            "provider": self.provider,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": self.scopes,
            "token_type": self.token_type,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "TokenSet":
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"])
        elif data.get("expires_in"):
            expires_at = datetime.now() + timedelta(seconds=int(data["expires_in"]))
        
        return cls(
            provider=data.get("provider", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=data.get("scopes", []) or data.get("scope", "").split(),
            token_type=data.get("token_type", "Bearer"),
        )


# =============================================================================
# Broker Client
# =============================================================================

class BrokerClient:
    """
    Client for the Ziggy OAuth broker.
    
    Handles OAuth flows through the central broker or self-hosted mode.
    """
    
    def __init__(self, config: Optional[BrokerConfig] = None):
        self.config = config or BrokerConfig.from_env()
        self._http_client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    # -------------------------------------------------------------------------
    # Provider Info
    # -------------------------------------------------------------------------
    
    async def get_available_providers(self) -> Dict[str, Dict]:
        """Get list of providers available on the broker."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.config.broker_url}/providers")
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.warning(f"Failed to get providers from broker: {e}")
        
        return {}
    
    async def is_broker_available(self) -> bool:
        """Check if the broker is reachable."""
        try:
            client = await self._get_client()
            response = await client.get(f"{self.config.broker_url}/", timeout=5.0)
            return response.status_code == 200
        except:
            return False
    
    # -------------------------------------------------------------------------
    # OAuth Flow
    # -------------------------------------------------------------------------
    
    def get_auth_url(
        self,
        provider: str,
        scopes: Optional[List[str]] = None,
        callback_url: Optional[str] = None,
    ) -> str:
        """
        Get the URL to start OAuth flow.
        
        Redirect the user to this URL to begin authentication.
        """
        callback = callback_url or self.config.local_callback
        
        params = {
            "callback": callback,
        }
        
        if scopes:
            params["scopes"] = ",".join(scopes)
        
        return f"{self.config.broker_url}/connect/{provider}?{urlencode(params)}"
    
    def parse_callback(self, url: str) -> Optional[TokenSet]:
        """
        Parse the callback URL to extract tokens.
        
        The broker redirects back with tokens encoded in the URL.
        """
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        tokens_encoded = params.get("tokens", [None])[0]
        if not tokens_encoded:
            return None
        
        try:
            # Decode base64 JSON
            tokens_json = base64.urlsafe_b64decode(tokens_encoded).decode()
            tokens_data = json.loads(tokens_json)
            return TokenSet.from_dict(tokens_data)
        except Exception as e:
            logger.error(f"Failed to parse callback tokens: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Token Refresh
    # -------------------------------------------------------------------------
    
    async def refresh_token(
        self,
        provider: str,
        refresh_token: str,
    ) -> Optional[TokenSet]:
        """
        Refresh an access token via the broker.
        
        Returns new TokenSet with fresh access_token.
        """
        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.config.broker_url}/refresh/{provider}",
                json={"refresh_token": refresh_token},
            )
            
            if response.status_code == 200:
                data = response.json()
                data["provider"] = provider
                return TokenSet.from_dict(data)
            else:
                logger.error(f"Token refresh failed: {response.status_code} {response.text}")
                
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
        
        return None


# =============================================================================
# Singleton
# =============================================================================

_broker_client: Optional[BrokerClient] = None


def get_broker_client() -> BrokerClient:
    """Get the global broker client instance."""
    global _broker_client
    if _broker_client is None:
        _broker_client = BrokerClient()
    return _broker_client
