"""
Connector Base Classes

Foundation for all Apex connectors with standardized interface,
health monitoring, and credential management.

Every connector implements:
1. Metadata (name, provider, description, scopes)
2. Lifecycle (connect, disconnect, health_check)
3. Rate limiting and error handling
4. Status reporting

Usage:
    class MyConnector(Connector):
        name = "my_connector"
        provider = "my_service"
        description = "Does stuff with MyService"
        
        async def connect(self) -> bool:
            # Connect to service
            return True
        
        async def health_check(self) -> ConnectorHealth:
            return ConnectorHealth.HEALTHY
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, ClassVar, Dict, List, Optional, Set, Type
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


# =============================================================================
# Error Hierarchy
# =============================================================================

class ConnectorError(Exception):
    """Base exception for all connector errors."""

    def __init__(self, message: str, connector: str = "", provider: str = ""):
        self.connector = connector
        self.provider = provider
        super().__init__(message)


class AuthError(ConnectorError):
    """Authentication or authorization failure (401/403, expired token)."""
    pass


class RateLimitError(ConnectorError):
    """Rate limit exceeded (429). Includes retry_after hint when available."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
        **kwargs,
    ):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class ConnectorTimeoutError(ConnectorError):
    """Request timed out."""
    pass


class NotConnectedError(ConnectorError):
    """Operation attempted on a connector that is not connected."""
    pass


# =============================================================================
# Enums and Status Types
# =============================================================================

class ConnectorHealth(Enum):
    """Health status of a connector."""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # Working but with issues
    UNHEALTHY = "unhealthy"  # Not working
    DISCONNECTED = "disconnected"  # Not connected
    AUTH_REQUIRED = "auth_required"  # Needs re-authentication


class ProviderType(Enum):
    """Types of service providers."""
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    SLACK = "slack"
    DISCORD = "discord"
    GITHUB = "github"
    JIRA = "jira"
    TODOIST = "todoist"
    DROPBOX = "dropbox"
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"  
    TWILIO = "twilio"
    ZOOM = "zoom"
    WEB = "web"
    LOCAL = "local"
    CUSTOM = "custom"


class AuthType(Enum):
    """Authentication methods supported."""
    NONE = "none"  # No auth required
    API_KEY = "api_key"  # Simple API key
    OAUTH2 = "oauth2"  # OAuth 2.0 flow
    OAUTH2_PKCE = "oauth2_pkce"  # OAuth 2.0 with PKCE
    BASIC = "basic"  # Username/password
    TOKEN = "token"  # Bearer token
    CUSTOM = "custom"  # Service-specific


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ConnectorConfig:
    """Configuration for a connector instance."""
    enabled: bool = True
    auto_refresh: bool = True
    refresh_interval_minutes: int = 30
    timeout_seconds: int = 30
    retry_attempts: int = 3
    rate_limit_per_minute: int = 60
    custom_settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorCredentials:
    """Credentials for a connector."""
    provider: str
    auth_type: AuthType
    
    # OAuth fields
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_expiry: Optional[datetime] = None
    scopes: List[str] = field(default_factory=list)
    
    # API key / token fields
    api_key: Optional[str] = None
    
    # Basic auth fields
    username: Optional[str] = None
    password: Optional[str] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    @property
    def is_expired(self) -> bool:
        """Check if OAuth token is expired."""
        if not self.token_expiry:
            return False
        return datetime.now() >= self.token_expiry
    
    @property
    def needs_refresh(self) -> bool:
        """Check if token needs refresh (5 min buffer)."""
        if not self.token_expiry:
            return False
        buffer = timedelta(minutes=5)
        return datetime.now() >= (self.token_expiry - buffer)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict (excluding sensitive data)."""
        return {
            "provider": self.provider,
            "auth_type": self.auth_type.value,
            "scopes": self.scopes,
            "has_token": bool(self.access_token),
            "has_refresh": bool(self.refresh_token),
            "token_expiry": self.token_expiry.isoformat() if self.token_expiry else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ConnectorStatus:
    """Current status of a connector."""
    name: str
    provider: str
    health: ConnectorHealth
    connected: bool
    authenticated: bool
    last_check: Optional[datetime] = None
    last_error: Optional[str] = None
    operations_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "name": self.name,
            "provider": self.provider,
            "health": self.health.value,
            "connected": self.connected,
            "authenticated": self.authenticated,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "last_error": self.last_error,
            "operations_count": self.operations_count,
            "error_count": self.error_count,
            "avg_latency_ms": self.avg_latency_ms,
        }


@dataclass
class ConnectorCapability:
    """Describes a capability/operation a connector provides."""
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    returns: str = "Dict"
    requires_auth: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "returns": self.returns,
            "requires_auth": self.requires_auth,
        }


# =============================================================================
# Connector Info (for discovery/registration)
# =============================================================================

@dataclass
class ConnectorInfo:
    """Information about a connector for registration/discovery."""
    name: str
    provider: ProviderType
    description: str
    auth_type: AuthType
    capabilities: List[str]
    required_scopes: List[str] = field(default_factory=list)
    optional_scopes: List[str] = field(default_factory=list)
    setup_url: Optional[str] = None
    docs_url: Optional[str] = None
    icon: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider.value,
            "description": self.description,
            "auth_type": self.auth_type.value,
            "capabilities": self.capabilities,
            "required_scopes": self.required_scopes,
            "optional_scopes": self.optional_scopes,
            "setup_url": self.setup_url,
            "docs_url": self.docs_url,
            "icon": self.icon,
        }


# =============================================================================
# Base Connector Class
# =============================================================================

class Connector(ABC):
    """
    Abstract base class for all Apex connectors.
    
    Every connector must implement:
    - name: Unique identifier for the connector
    - provider: Service provider type
    - info: ConnectorInfo with metadata
    - connect(): Establish connection
    - disconnect(): Close connection
    - health_check(): Verify health
    - get_capabilities(): List available operations
    """
    
    # Class-level metadata (override in subclasses)
    name: ClassVar[str] = "base_connector"
    provider: ClassVar[ProviderType] = ProviderType.CUSTOM
    description: ClassVar[str] = "Base connector"
    auth_type: ClassVar[AuthType] = AuthType.NONE
    
    def __init__(self, config: Optional[ConnectorConfig] = None):
        """
        Initialize connector with optional config.
        
        Args:
            config: Optional configuration override
        """
        self._config = config or ConnectorConfig()
        self._connected = False
        self._authenticated = False
        self._credentials: Optional[ConnectorCredentials] = None
        self._last_health_check: Optional[datetime] = None
        self._last_error: Optional[str] = None
        self._operation_count = 0
        self._error_count = 0
        self._latency_sum = 0.0
        # Circuit breaker state
        self._cb_failures = 0
        self._cb_open_until: Optional[float] = None
        self._CB_THRESHOLD = 5       # consecutive failures to trip
        self._CB_COOLDOWN = 60.0     # seconds before retrying
    
    # -------------------------------------------------------------------------
    # Abstract methods (must implement)
    # -------------------------------------------------------------------------
    
    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to the service.
        
        Returns:
            True if connected successfully
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """
        Disconnect from the service.
        
        Returns:
            True if disconnected successfully
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> ConnectorHealth:
        """
        Check if the connector is healthy.
        
        Returns:
            Current health status
        """
        pass
    
    @abstractmethod
    def get_capabilities(self) -> List[ConnectorCapability]:
        """
        Get list of capabilities this connector provides.
        
        Returns:
            List of capability descriptors
        """
        pass
    
    # -------------------------------------------------------------------------
    # Optional overrides
    # -------------------------------------------------------------------------
    
    @classmethod
    def get_info(cls) -> ConnectorInfo:
        """
        Get connector metadata for registration.
        
        Override to customize.
        """
        return ConnectorInfo(
            name=cls.name,
            provider=cls.provider,
            description=cls.description,
            auth_type=cls.auth_type,
            capabilities=[],
        )
    
    @classmethod
    def get_setup_instructions(cls) -> str:
        """
        Get human-readable setup instructions.
        
        Override to customize.
        """
        return f"Setup instructions for {cls.name} not available."
    
    async def refresh_credentials(self) -> bool:
        """
        Refresh OAuth credentials if needed.
        
        Override for OAuth connectors.
        """
        return True
    
    # -------------------------------------------------------------------------
    # Common methods (inherit as-is)
    # -------------------------------------------------------------------------
    
    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected
    
    @property
    def is_authenticated(self) -> bool:
        """Check if authenticated."""
        return self._authenticated
    
    @property
    def config(self) -> ConnectorConfig:
        """Get current config."""
        return self._config
    
    async def get_status(self) -> ConnectorStatus:
        """Get current connector status."""
        health = await self.health_check()
        self._last_health_check = datetime.now()
        
        return ConnectorStatus(
            name=self.name,
            provider=self.provider.value if isinstance(self.provider, ProviderType) else str(self.provider),
            health=health,
            connected=self._connected,
            authenticated=self._authenticated,
            last_check=self._last_health_check,
            last_error=self._last_error,
            operations_count=self._operation_count,
            error_count=self._error_count,
            avg_latency_ms=self._latency_sum / max(1, self._operation_count),
        )
    
    def record_operation(self, latency_ms: float, success: bool = True):
        """Record an operation for metrics."""
        self._operation_count += 1
        self._latency_sum += latency_ms
        if not success:
            self._error_count += 1
    
    def record_error(self, error: str):
        """Record an error."""
        self._last_error = error
        self._error_count += 1
        logger.error(f"[{self.name}] {error}")

    async def _retry_with_backoff(self, coro_factory, max_retries: int = 3):
        """Execute an async callable with exponential backoff on transient errors.

        Includes circuit breaker (stop hammering dead services) and
        transparent auth refresh (catch 401 → refresh → retry once).

        Args:
            coro_factory: A zero-arg callable that returns a new coroutine each
                          call (e.g., ``lambda: self._client.get(url)``).
            max_retries: Maximum number of retry attempts.

        Returns:
            The result of the successful coroutine.

        Raises:
            AuthError: After refresh + reconnect both fail.
            RateLimitError: After exhausting retries or if no retry_after.
            ConnectorTimeoutError: After exhausting retries.
            ConnectorError: After exhausting retries for other transient errors.
        """
        # --- Circuit breaker: if tripped, fail fast ---
        if self._cb_open_until is not None:
            if time.monotonic() < self._cb_open_until:
                raise ConnectorError(
                    f"{self.name} circuit breaker open — backing off for "
                    f"{self._cb_open_until - time.monotonic():.0f}s",
                    connector=self.name,
                )
            # Cooldown elapsed, allow one probe
            self._cb_open_until = None
            logger.info(f"[{self.name}] Circuit breaker half-open, probing...")

        last_exc: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                start = time.monotonic()
                result = await coro_factory()
                latency = (time.monotonic() - start) * 1000
                self.record_operation(latency, success=True)
                self._cb_failures = 0  # reset on success
                return result
            except AuthError as e:
                # Transparent auth refresh: try refresh → retry once
                logger.warning(f"[{self.name}] Auth error, attempting token refresh...")
                try:
                    refreshed = await self.refresh_credentials()
                    if refreshed:
                        logger.info(f"[{self.name}] Token refreshed, retrying...")
                        result = await coro_factory()
                        self._cb_failures = 0
                        return result
                except Exception:
                    pass
                # Refresh failed — try disconnect + reconnect
                logger.warning(f"[{self.name}] Refresh failed, attempting reconnect...")
                try:
                    await self.disconnect()
                    connected = await self.connect()
                    if connected:
                        logger.info(f"[{self.name}] Reconnected, retrying...")
                        result = await coro_factory()
                        self._cb_failures = 0
                        return result
                except Exception:
                    pass
                # All recovery failed
                self._cb_failures += 1
                if self._cb_failures >= self._CB_THRESHOLD:
                    self._cb_open_until = time.monotonic() + self._CB_COOLDOWN
                    logger.error(f"[{self.name}] Circuit breaker OPEN after {self._cb_failures} failures")
                self.record_error(str(e))
                raise
            except RateLimitError as e:
                last_exc = e
                delay = e.retry_after if e.retry_after else 2 ** attempt
                if attempt < max_retries:
                    logger.warning(
                        f"[{self.name}] Rate limited, retry {attempt + 1}/{max_retries} "
                        f"in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                self._cb_failures += 1
                self.record_error(str(e))
                raise
            except (ConnectorTimeoutError, asyncio.TimeoutError) as e:
                last_exc = e
                delay = 2 ** attempt
                if attempt < max_retries:
                    logger.warning(
                        f"[{self.name}] Timeout, retry {attempt + 1}/{max_retries} "
                        f"in {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                self._cb_failures += 1
                self.record_error(str(e))
                raise ConnectorTimeoutError(
                    str(e), connector=self.name
                ) from e
            except ConnectorError:
                self._cb_failures += 1
                raise  # Don't retry unknown connector errors
            except Exception as e:
                last_exc = e
                # SSL errors won't self-heal — fail fast
                err_str = str(e)
                if "SSL" in err_str or "WRONG_VERSION_NUMBER" in err_str or "CERTIFICATE" in err_str.upper():
                    logger.error(f"[{self.name}] SSL error (not retryable): {e}")
                    self._cb_failures += 1
                    self.record_error(err_str)
                    raise ConnectorError(err_str, connector=self.name) from e
                delay = 2 ** attempt
                if attempt < max_retries:
                    logger.warning(
                        f"[{self.name}] Transient error, retry {attempt + 1}/{max_retries} "
                        f"in {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                self._cb_failures += 1
                self.record_error(str(e))
                raise ConnectorError(
                    str(e), connector=self.name
                ) from e

        # Trip breaker if enough consecutive failures
        if self._cb_failures >= self._CB_THRESHOLD:
            self._cb_open_until = time.monotonic() + self._CB_COOLDOWN
            logger.error(f"[{self.name}] Circuit breaker OPEN after {self._cb_failures} failures")

        # Should not reach here, but just in case
        raise ConnectorError(str(last_exc), connector=self.name)  # pragma: no cover

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name} connected={self._connected}>"


# =============================================================================
# Mixin Classes for Common Patterns
# =============================================================================

class OAuthConnectorMixin:
    """
    Mixin for OAuth-based connectors.
    
    Provides:
    - Token storage and refresh
    - OAuth flow helpers
    - Scope management
    """
    
    _credentials: Optional[ConnectorCredentials]
    _authenticated: bool
    
    async def set_oauth_credentials(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
        scopes: Optional[List[str]] = None,
    ) -> None:
        """Set OAuth credentials."""
        expiry = None
        if expires_in:
            expiry = datetime.now() + timedelta(seconds=expires_in)
        
        self._credentials = ConnectorCredentials(
            provider=getattr(self, 'provider', 'unknown'),
            auth_type=AuthType.OAUTH2,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=expiry,
            scopes=scopes or [],
        )
        self._authenticated = True
    
    @property
    def needs_token_refresh(self) -> bool:
        """Check if token needs refresh."""
        if not self._credentials:
            return False
        return self._credentials.needs_refresh
    
    @property
    def oauth_scopes(self) -> List[str]:
        """Get current OAuth scopes."""
        if not self._credentials:
            return []
        return self._credentials.scopes


class APIKeyConnectorMixin:
    """
    Mixin for API key-based connectors.
    
    Provides:
    - API key storage
    - Header injection
    """
    
    _credentials: Optional[ConnectorCredentials]
    _authenticated: bool
    
    def set_api_key(self, api_key: str) -> None:
        """Set API key."""
        self._credentials = ConnectorCredentials(
            provider=getattr(self, 'provider', 'unknown'),
            auth_type=AuthType.API_KEY,
            api_key=api_key,
        )
        self._authenticated = True
    
    @property
    def api_key(self) -> Optional[str]:
        """Get API key if set."""
        if not self._credentials:
            return None
        return self._credentials.api_key
    
    def get_auth_header(self) -> Dict[str, str]:
        """Get authorization header dict."""
        if not self._credentials or not self._credentials.api_key:
            return {}
        # Default to Bearer, override if needed
        return {"Authorization": f"Bearer {self._credentials.api_key}"}


class RateLimitMixin:
    """
    Mixin for rate limiting.
    
    Provides:
    - Token bucket rate limiting
    - Backoff handling
    """
    
    _rate_limit_tokens: float = 0
    _rate_limit_last_update: Optional[datetime] = None
    _config: ConnectorConfig
    
    async def acquire_rate_limit(self) -> bool:
        """
        Acquire a rate limit token.
        
        Returns True if operation can proceed, False if rate limited.
        """
        now = datetime.now()
        
        # Initialize on first call
        if self._rate_limit_last_update is None:
            self._rate_limit_tokens = float(self._config.rate_limit_per_minute)
            self._rate_limit_last_update = now
            return True
        
        # Refill tokens based on elapsed time
        elapsed = (now - self._rate_limit_last_update).total_seconds()
        refill = elapsed * (self._config.rate_limit_per_minute / 60.0)
        self._rate_limit_tokens = min(
            float(self._config.rate_limit_per_minute),
            self._rate_limit_tokens + refill
        )
        self._rate_limit_last_update = now
        
        # Check if we have tokens
        if self._rate_limit_tokens >= 1.0:
            self._rate_limit_tokens -= 1.0
            return True
        
        return False


# =============================================================================
# Standalone Retry Utility
# =============================================================================

async def retry_with_backoff(
    coro_factory,
    max_retries: int = 3,
    connector_name: str = "",
):
    """Execute an async callable with exponential backoff.

    Standalone version for connectors that don't inherit from Connector.

    Args:
        coro_factory: Zero-arg callable returning a new coroutine each call.
        max_retries: Maximum retry attempts.
        connector_name: Name for log messages.

    Raises:
        AuthError: Immediately (never retried).
        The last exception after retries are exhausted.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except AuthError:
            raise
        except RateLimitError as e:
            last_exc = e
            delay = e.retry_after if e.retry_after else 2 ** attempt
        except (ConnectorTimeoutError, asyncio.TimeoutError) as e:
            last_exc = e
            delay = 2 ** attempt
        except ConnectorError:
            raise
        except Exception as e:
            last_exc = e
            # SSL errors won't self-heal — fail fast
            err_str = str(e)
            if "SSL" in err_str or "WRONG_VERSION_NUMBER" in err_str or "CERTIFICATE" in err_str.upper():
                raise
            delay = 2 ** attempt

        if attempt < max_retries:
            logger.warning(
                f"[{connector_name}] Retry {attempt + 1}/{max_retries} in {delay:.1f}s: {last_exc}"
            )
            await asyncio.sleep(delay)
            continue
        raise last_exc  # type: ignore[misc]


# =============================================================================
# Type Exports
# =============================================================================

__all__ = [
    # Errors
    "ConnectorError",
    "AuthError",
    "RateLimitError",
    "ConnectorTimeoutError",
    "NotConnectedError",
    # Retry utility
    "retry_with_backoff",
    # Enums
    "ConnectorHealth",
    "ProviderType", 
    "AuthType",
    # Data classes
    "ConnectorConfig",
    "ConnectorCredentials",
    "ConnectorStatus",
    "ConnectorCapability",
    "ConnectorInfo",
    # Base class
    "Connector",
    # Mixins
    "OAuthConnectorMixin",
    "APIKeyConnectorMixin",
    "RateLimitMixin",
]
