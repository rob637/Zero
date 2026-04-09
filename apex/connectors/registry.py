"""
Connector Registry

Central registry for all cloud service connectors.
Maps connectors to primitives and manages connection lifecycle.

Features:
- Register connectors with metadata
- Track connection status per provider
- Map primitives to available providers
- Multi-provider support (e.g., EMAIL → Gmail + Outlook)
- Connection health monitoring

Usage:
    from apex.connectors.registry import ConnectorRegistry, get_registry
    
    registry = get_registry()
    
    # Check what's connected
    connected = registry.get_connected_providers()
    
    # Get providers for a primitive
    email_providers = registry.get_providers_for_primitive("EMAIL")
    
    # Connect to a provider
    await registry.connect("google")
    
    # Get connector instance
    gmail = registry.get_connector("gmail")
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Type, Union

import logging
logger = logging.getLogger(__name__)

from .credentials import CredentialStore, get_credential_store, StoredCredential


class ConnectionStatus(Enum):
    """Status of a connector connection."""
    DISCONNECTED = "disconnected"      # Not connected
    CONNECTING = "connecting"          # OAuth/auth in progress
    CONNECTED = "connected"            # Successfully connected
    ERROR = "error"                    # Connection failed
    EXPIRED = "expired"                # Token expired, needs refresh
    NEEDS_SETUP = "needs_setup"        # Missing client credentials


@dataclass
class ConnectorHealth:
    """Health status of a connector."""
    status: ConnectionStatus
    last_check: datetime
    error_message: Optional[str] = None
    latency_ms: Optional[float] = None
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset: Optional[datetime] = None
    
    @property
    def is_healthy(self) -> bool:
        return self.status == ConnectionStatus.CONNECTED


@dataclass
class ConnectorMetadata:
    """Metadata about a registered connector."""
    name: str                          # Unique identifier (e.g., "gmail", "outlook")
    display_name: str                  # Human-readable name
    provider: str                      # Provider name (e.g., "google", "microsoft")
    primitives: List[str]              # Primitives this connector supports
    scopes: List[str]                  # Required OAuth scopes
    connector_class: Type              # The connector class
    description: str = ""              # Description of the connector
    icon: str = ""                     # Icon name or URL
    setup_url: str = ""                # URL for setup instructions
    requires_client_creds: bool = True # Whether client credentials are needed
    is_premium: bool = False           # Whether this is a premium connector
    extra: Dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """
    Abstract base class for all connectors.
    
    All connectors must implement these methods to integrate
    with the registry and credential system.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique connector name."""
        pass
    
    @property
    @abstractmethod
    def provider(self) -> str:
        """Provider name (google, microsoft, etc.)."""
        pass
    
    @abstractmethod
    async def connect(self, credentials: Optional[StoredCredential] = None) -> bool:
        """
        Connect to the service.
        
        Args:
            credentials: Optional pre-loaded credentials
        
        Returns:
            True if connected successfully
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from the service."""
        pass
    
    @abstractmethod
    async def check_health(self) -> ConnectorHealth:
        """Check connection health."""
        pass
    
    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if currently connected."""
        pass


class ConnectorRegistry:
    """
    Central registry for all connectors.
    
    Manages:
    - Connector registration and discovery
    - Connection lifecycle (connect, disconnect, health check)
    - Primitive-to-provider mapping
    - Multi-provider selection
    """
    
    def __init__(self, credential_store: Optional[CredentialStore] = None):
        self._credential_store = credential_store or get_credential_store()
        
        # Registered connector metadata
        self._connectors: Dict[str, ConnectorMetadata] = {}
        
        # Active connector instances
        self._instances: Dict[str, BaseConnector] = {}
        
        # Connection status cache
        self._status: Dict[str, ConnectorHealth] = {}
        
        # Primitive to connector mapping
        self._primitive_map: Dict[str, List[str]] = {}
        
        # Provider to connector mapping
        self._provider_map: Dict[str, List[str]] = {}
        
        # Preferred connector per primitive
        self._preferences: Dict[str, str] = {}
        
        # Load built-in connectors
        self._register_builtin_connectors()
    
    def _register_builtin_connectors(self):
        """Register all built-in connectors."""
        # This will be populated with actual connector metadata
        self._register_google_connectors()
        self._register_microsoft_connectors()
        self._register_other_connectors()
    
    def _register_google_connectors(self):
        """Register Google Suite connectors."""
        from .gmail import GmailConnector
        from .calendar import CalendarConnector
        from .drive import DriveConnector
        from .contacts import ContactsConnector
        
        self.register(ConnectorMetadata(
            name="gmail",
            display_name="Gmail",
            provider="google",
            primitives=["EMAIL"],
            scopes=["gmail"],
            connector_class=GmailConnector,
            description="Send, read, and search Gmail messages",
            icon="gmail",
            setup_url="https://console.cloud.google.com/",
        ))
        
        self.register(ConnectorMetadata(
            name="google_calendar",
            display_name="Google Calendar",
            provider="google",
            primitives=["CALENDAR", "MEETING"],
            scopes=["calendar"],
            connector_class=CalendarConnector,
            description="Manage Google Calendar events",
            icon="calendar",
            setup_url="https://console.cloud.google.com/",
        ))
        
        self.register(ConnectorMetadata(
            name="google_drive",
            display_name="Google Drive",
            provider="google",
            primitives=["CLOUD_STORAGE", "DOCUMENT"],
            scopes=["drive"],
            connector_class=DriveConnector,
            description="Access Google Drive files",
            icon="drive",
            setup_url="https://console.cloud.google.com/",
        ))
        
        self.register(ConnectorMetadata(
            name="google_contacts",
            display_name="Google Contacts",
            provider="google",
            primitives=["CONTACTS"],
            scopes=["contacts"],
            connector_class=ContactsConnector,
            description="Access Google Contacts",
            icon="contacts",
            setup_url="https://console.cloud.google.com/",
        ))
        
        try:
            from .google_sheets import SheetsConnector as GoogleSheetsConnector
            self.register(ConnectorMetadata(
                name="google_sheets",
                display_name="Google Sheets",
                provider="google",
                primitives=["SPREADSHEET"],
                scopes=["sheets"],
                connector_class=GoogleSheetsConnector,
                description="Access and edit Google Sheets spreadsheets",
                icon="sheets",
                setup_url="https://console.cloud.google.com/",
            ))
        except ImportError:
            pass
        
        try:
            from .google_slides import SlidesConnector as GoogleSlidesConnector
            self.register(ConnectorMetadata(
                name="google_slides",
                display_name="Google Slides",
                provider="google",
                primitives=["PRESENTATION"],
                scopes=["slides"],
                connector_class=GoogleSlidesConnector,
                description="Access and edit Google Slides presentations",
                icon="slides",
                setup_url="https://console.cloud.google.com/",
            ))
        except ImportError:
            pass
        
        try:
            from .google_photos import PhotosConnector as GooglePhotosConnector
            self.register(ConnectorMetadata(
                name="google_photos",
                display_name="Google Photos",
                provider="google",
                primitives=["PHOTO"],
                scopes=["photos"],
                connector_class=GooglePhotosConnector,
                description="Access Google Photos library and albums",
                icon="photos",
                setup_url="https://console.cloud.google.com/",
            ))
        except ImportError:
            pass
    
    def _register_microsoft_connectors(self):
        """Register Microsoft 365 connectors."""
        from .outlook import OutlookConnector
        from .outlook_calendar import OutlookCalendarConnector
        from .onedrive import OneDriveConnector
        from .microsoft_todo import MicrosoftTodoConnector
        
        self.register(ConnectorMetadata(
            name="outlook",
            display_name="Outlook",
            provider="microsoft",
            primitives=["EMAIL"],
            scopes=["mail.read", "mail.send"],
            connector_class=OutlookConnector,
            description="Send, read, and search Outlook messages",
            icon="outlook",
            setup_url="https://portal.azure.com/",
        ))
        
        self.register(ConnectorMetadata(
            name="outlook_calendar",
            display_name="Outlook Calendar",
            provider="microsoft",
            primitives=["CALENDAR", "MEETING"],
            scopes=["calendars.readwrite"],
            connector_class=OutlookCalendarConnector,
            description="Manage Outlook Calendar events",
            icon="calendar",
            setup_url="https://portal.azure.com/",
        ))
        
        self.register(ConnectorMetadata(
            name="onedrive",
            display_name="OneDrive",
            provider="microsoft",
            primitives=["CLOUD_STORAGE", "DOCUMENT"],
            scopes=["files.readwrite"],
            connector_class=OneDriveConnector,
            description="Access OneDrive files",
            icon="onedrive",
            setup_url="https://portal.azure.com/",
        ))
        
        self.register(ConnectorMetadata(
            name="microsoft_todo",
            display_name="Microsoft To-Do",
            provider="microsoft",
            primitives=["TASK"],
            scopes=["tasks.readwrite"],
            connector_class=MicrosoftTodoConnector,
            description="Manage Microsoft To-Do tasks",
            icon="todo",
            setup_url="https://portal.azure.com/",
        ))
        
        try:
            from .onenote import OneNoteConnector
            self.register(ConnectorMetadata(
                name="onenote",
                display_name="Microsoft OneNote",
                provider="microsoft",
                primitives=["NOTES"],
                scopes=["notes.readwrite"],
                connector_class=OneNoteConnector,
                description="Access and manage OneNote notebooks and pages",
                icon="onenote",
                setup_url="https://portal.azure.com/",
            ))
        except ImportError:
            pass
        
        try:
            from .microsoft_excel import ExcelConnector
            self.register(ConnectorMetadata(
                name="microsoft_excel",
                display_name="Microsoft Excel Online",
                provider="microsoft",
                primitives=["SPREADSHEET"],
                scopes=["files.readwrite"],
                connector_class=ExcelConnector,
                description="Read, write, and manage Excel workbooks via Graph API",
                icon="excel",
                setup_url="https://portal.azure.com/",
            ))
        except ImportError:
            pass
        
        try:
            from .microsoft_powerpoint import PowerPointConnector
            self.register(ConnectorMetadata(
                name="microsoft_powerpoint",
                display_name="Microsoft PowerPoint Online",
                provider="microsoft",
                primitives=["PRESENTATION"],
                scopes=["files.readwrite"],
                connector_class=PowerPointConnector,
                description="Create and manage PowerPoint presentations via Graph API",
                icon="powerpoint",
                setup_url="https://portal.azure.com/",
            ))
        except ImportError:
            pass
        
        try:
            from .microsoft_contacts import MicrosoftContactsConnector
            self.register(ConnectorMetadata(
                name="microsoft_contacts",
                display_name="Microsoft Contacts",
                provider="microsoft",
                primitives=["CONTACTS"],
                scopes=["contacts.readwrite"],
                connector_class=MicrosoftContactsConnector,
                description="Manage Microsoft 365 contacts",
                icon="contacts",
                setup_url="https://portal.azure.com/",
            ))
        except ImportError:
            pass
    
    def _register_other_connectors(self):
        """Register other connectors (Slack, GitHub, etc.)."""
        try:
            from .slack import SlackConnector
            self.register(ConnectorMetadata(
                name="slack",
                display_name="Slack",
                provider="slack",
                primitives=["CHAT", "MESSAGE"],
                scopes=["chat:write", "channels:read"],
                connector_class=SlackConnector,
                description="Send messages to Slack channels",
                icon="slack",
                setup_url="https://api.slack.com/apps",
            ))
        except ImportError:
            pass
        
        try:
            from .github import GitHubConnector
            self.register(ConnectorMetadata(
                name="github",
                display_name="GitHub",
                provider="github",
                primitives=["DEVTOOLS"],
                scopes=["repo", "read:user"],
                connector_class=GitHubConnector,
                description="Access GitHub repositories and issues",
                icon="github",
                setup_url="https://github.com/settings/tokens",
                requires_client_creds=False,  # Just needs personal access token
            ))
        except ImportError:
            pass
        
        try:
            from .discord import DiscordConnector
            self.register(ConnectorMetadata(
                name="discord",
                display_name="Discord",
                provider="discord",
                primitives=["CHAT"],
                scopes=[],
                connector_class=DiscordConnector,
                description="Send messages to Discord channels",
                icon="discord",
                setup_url="https://discord.com/developers/applications",
            ))
        except ImportError:
            pass
        
        try:
            from .spotify import SpotifyConnector
            self.register(ConnectorMetadata(
                name="spotify",
                display_name="Spotify",
                provider="spotify",
                primitives=["MEDIA"],
                scopes=["user-read-playback-state", "user-modify-playback-state"],
                connector_class=SpotifyConnector,
                description="Control Spotify playback",
                icon="spotify",
                setup_url="https://developer.spotify.com/dashboard",
            ))
        except ImportError:
            pass
        
        try:
            from .twilio_sms import TwilioSMSConnector
            self.register(ConnectorMetadata(
                name="twilio",
                display_name="Twilio SMS",
                provider="twilio",
                primitives=["SMS", "MESSAGE"],
                scopes=[],
                connector_class=TwilioSMSConnector,
                description="Send SMS via Twilio",
                icon="twilio",
                setup_url="https://console.twilio.com/",
                requires_client_creds=False,
            ))
        except ImportError:
            pass
        
        try:
            from .todoist import TodoistConnector
            self.register(ConnectorMetadata(
                name="todoist",
                display_name="Todoist",
                provider="todoist",
                primitives=["TASK"],
                scopes=[],
                connector_class=TodoistConnector,
                description="Manage Todoist tasks",
                icon="todoist",
                setup_url="https://todoist.com/app/settings/integrations",
            ))
        except ImportError:
            pass
        
        try:
            from .dropbox import DropboxConnector
            self.register(ConnectorMetadata(
                name="dropbox",
                display_name="Dropbox",
                provider="dropbox",
                primitives=["CLOUD_STORAGE"],
                scopes=["files.content.write", "files.content.read"],
                connector_class=DropboxConnector,
                description="Access Dropbox files",
                icon="dropbox",
                setup_url="https://www.dropbox.com/developers/apps",
            ))
        except ImportError:
            pass
        
        try:
            from .jira import JiraConnector
            self.register(ConnectorMetadata(
                name="jira",
                display_name="Jira",
                provider="atlassian",
                primitives=["TASK", "DEVTOOLS"],
                scopes=["read:jira-work", "write:jira-work"],
                connector_class=JiraConnector,
                description="Manage Jira issues",
                icon="jira",
                setup_url="https://id.atlassian.com/manage-profile/security/api-tokens",
            ))
        except ImportError:
            pass
        
        try:
            from .teams import TeamsConnector
            self.register(ConnectorMetadata(
                name="teams",
                display_name="Microsoft Teams",
                provider="microsoft",
                primitives=["CHAT", "MEETING"],
                scopes=["chat.read", "chat.send"],
                connector_class=TeamsConnector,
                description="Send messages to Teams channels",
                icon="teams",
                setup_url="https://portal.azure.com/",
            ))
        except ImportError:
            pass
        
        try:
            from .twitter import TwitterConnector
            self.register(ConnectorMetadata(
                name="twitter",
                display_name="Twitter/X",
                provider="twitter",
                primitives=["SOCIAL"],
                scopes=["tweet.read", "tweet.write", "users.read"],
                connector_class=TwitterConnector,
                description="Post tweets and manage Twitter/X account",
                icon="twitter",
                setup_url="https://developer.twitter.com/en/portal/dashboard",
            ))
        except ImportError:
            pass
        
        try:
            from .smartthings import SmartThingsConnector
            self.register(ConnectorMetadata(
                name="smartthings",
                display_name="Samsung SmartThings",
                provider="smartthings",
                primitives=["IOT", "HOME_AUTOMATION"],
                scopes=[],
                connector_class=SmartThingsConnector,
                description="Control smart home devices via SmartThings",
                icon="smartthings",
                setup_url="https://account.smartthings.com/tokens",
                requires_client_creds=False,  # Just needs personal access token
            ))
        except ImportError:
            pass
        
        try:
            from .weather import WeatherConnector
            self.register(ConnectorMetadata(
                name="weather",
                display_name="Weather",
                provider="weather",
                primitives=["WEATHER"],
                scopes=[],
                connector_class=WeatherConnector,
                description="Current weather, forecasts, and air quality via OpenWeatherMap",
                icon="weather",
                setup_url="https://openweathermap.org/api",
                requires_client_creds=False,
            ))
        except ImportError:
            pass
        
        try:
            from .news import NewsConnector
            self.register(ConnectorMetadata(
                name="news",
                display_name="News",
                provider="news",
                primitives=["NEWS"],
                scopes=[],
                connector_class=NewsConnector,
                description="Top headlines, news search, and source discovery via NewsAPI",
                icon="news",
                setup_url="https://newsapi.org/register",
                requires_client_creds=False,
            ))
        except ImportError:
            pass
        
        try:
            from .notion import NotionConnector
            self.register(ConnectorMetadata(
                name="notion",
                display_name="Notion",
                provider="notion",
                primitives=["NOTES", "DATABASE", "WIKI"],
                scopes=[],
                connector_class=NotionConnector,
                description="Pages, databases, content blocks, comments, and search in Notion",
                icon="notion",
                setup_url="https://www.notion.so/my-integrations",
                requires_client_creds=False,
            ))
        except ImportError:
            pass
    
    # ========================================================================
    # Registration
    # ========================================================================
    
    def register(self, metadata: ConnectorMetadata) -> bool:
        """
        Register a connector.
        
        Args:
            metadata: Connector metadata
        
        Returns:
            True if registered successfully
        """
        if metadata.name in self._connectors:
            logger.warning(f"Connector {metadata.name} already registered, overwriting")
        
        self._connectors[metadata.name] = metadata
        
        # Update primitive mapping
        for primitive in metadata.primitives:
            if primitive not in self._primitive_map:
                self._primitive_map[primitive] = []
            if metadata.name not in self._primitive_map[primitive]:
                self._primitive_map[primitive].append(metadata.name)
        
        # Update provider mapping
        if metadata.provider not in self._provider_map:
            self._provider_map[metadata.provider] = []
        if metadata.name not in self._provider_map[metadata.provider]:
            self._provider_map[metadata.provider].append(metadata.name)
        
        logger.debug(f"Registered connector: {metadata.name}")
        return True
    
    def unregister(self, name: str) -> bool:
        """Unregister a connector."""
        if name not in self._connectors:
            return False
        
        metadata = self._connectors.pop(name)
        
        # Clean up mappings
        for primitive in metadata.primitives:
            if primitive in self._primitive_map:
                self._primitive_map[primitive] = [
                    c for c in self._primitive_map[primitive] if c != name
                ]
        
        if metadata.provider in self._provider_map:
            self._provider_map[metadata.provider] = [
                c for c in self._provider_map[metadata.provider] if c != name
            ]
        
        # Clean up instance
        if name in self._instances:
            del self._instances[name]
        
        return True
    
    # ========================================================================
    # Discovery
    # ========================================================================
    
    def list_connectors(self) -> List[ConnectorMetadata]:
        """List all registered connectors."""
        return list(self._connectors.values())
    
    def get_metadata(self, name: str) -> Optional[ConnectorMetadata]:
        """Get metadata for a connector."""
        return self._connectors.get(name)
    
    def get_providers(self) -> List[str]:
        """List all unique providers."""
        return list(self._provider_map.keys())
    
    def get_connectors_for_provider(self, provider: str) -> List[str]:
        """Get all connectors for a provider."""
        return self._provider_map.get(provider, [])
    
    def get_providers_for_primitive(self, primitive: str) -> List[str]:
        """
        Get available connectors for a primitive.
        
        Args:
            primitive: Primitive name (e.g., "EMAIL", "CALENDAR")
        
        Returns:
            List of connector names that support this primitive
        """
        return self._primitive_map.get(primitive.upper(), [])
    
    def get_connected_providers(self) -> List[str]:
        """Get list of providers that are currently connected."""
        connected = []
        for provider in self._provider_map:
            # Check if any connector for this provider is connected
            for connector_name in self._provider_map[provider]:
                if self._credential_store.has_valid(provider):
                    connected.append(provider)
                    break
        return connected
    
    def get_available_primitives(self) -> Dict[str, List[str]]:
        """
        Get primitives and their available connectors.
        
        Returns:
            Dict mapping primitive names to list of connector names
        """
        return dict(self._primitive_map)
    
    # ========================================================================
    # Preferences
    # ========================================================================
    
    def set_preferred_connector(self, primitive: str, connector_name: str) -> bool:
        """
        Set the preferred connector for a primitive.
        
        When multiple connectors support the same primitive,
        this determines which one to use by default.
        
        Args:
            primitive: Primitive name
            connector_name: Connector to prefer
        
        Returns:
            True if set successfully
        """
        primitive = primitive.upper()
        
        if connector_name not in self._connectors:
            logger.error(f"Unknown connector: {connector_name}")
            return False
        
        if connector_name not in self.get_providers_for_primitive(primitive):
            logger.error(f"Connector {connector_name} doesn't support {primitive}")
            return False
        
        self._preferences[primitive] = connector_name
        return True
    
    def get_preferred_connector(self, primitive: str) -> Optional[str]:
        """
        Get the preferred connector for a primitive.
        
        Returns:
            Connector name or None if no preference set
        """
        primitive = primitive.upper()
        
        # Check explicit preference
        if primitive in self._preferences:
            pref = self._preferences[primitive]
            # Verify it's still connected
            metadata = self.get_metadata(pref)
            if metadata and self._credential_store.has_valid(metadata.provider):
                return pref
        
        # Fall back to first connected provider
        for connector_name in self.get_providers_for_primitive(primitive):
            metadata = self.get_metadata(connector_name)
            if metadata and self._credential_store.has_valid(metadata.provider):
                return connector_name
        
        # Fall back to first available
        connectors = self.get_providers_for_primitive(primitive)
        return connectors[0] if connectors else None
    
    # ========================================================================
    # Connection Management
    # ========================================================================
    
    async def connect(self, connector_name: str) -> bool:
        """
        Connect to a service.
        
        This will initiate OAuth flow if needed.
        
        Args:
            connector_name: Name of the connector
        
        Returns:
            True if connected successfully
        """
        metadata = self.get_metadata(connector_name)
        if not metadata:
            logger.error(f"Unknown connector: {connector_name}")
            return False
        
        # Update status
        self._status[connector_name] = ConnectorHealth(
            status=ConnectionStatus.CONNECTING,
            last_check=datetime.utcnow(),
        )
        
        try:
            # Get or create connector instance
            if connector_name not in self._instances:
                self._instances[connector_name] = metadata.connector_class()
            
            connector = self._instances[connector_name]
            
            # Load credentials if available
            creds = self._credential_store.get(metadata.provider)
            
            # Connect
            success = await connector.connect(creds)
            
            self._status[connector_name] = ConnectorHealth(
                status=ConnectionStatus.CONNECTED if success else ConnectionStatus.ERROR,
                last_check=datetime.utcnow(),
                error_message=None if success else "Connection failed",
            )
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to connect {connector_name}: {e}")
            self._status[connector_name] = ConnectorHealth(
                status=ConnectionStatus.ERROR,
                last_check=datetime.utcnow(),
                error_message=str(e),
            )
            return False
    
    async def disconnect(self, connector_name: str) -> bool:
        """
        Disconnect from a service.
        
        This doesn't revoke credentials, just disconnects the session.
        """
        if connector_name not in self._instances:
            return True
        
        try:
            connector = self._instances[connector_name]
            await connector.disconnect()
            
            self._status[connector_name] = ConnectorHealth(
                status=ConnectionStatus.DISCONNECTED,
                last_check=datetime.utcnow(),
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to disconnect {connector_name}: {e}")
            return False
    
    async def connect_provider(self, provider: str) -> Dict[str, bool]:
        """
        Connect all connectors for a provider.
        
        Args:
            provider: Provider name (google, microsoft, etc.)
        
        Returns:
            Dict mapping connector names to success status
        """
        results = {}
        
        for connector_name in self.get_connectors_for_provider(provider):
            results[connector_name] = await self.connect(connector_name)
        
        return results
    
    def get_connector(self, name: str) -> Optional[BaseConnector]:
        """
        Get a connector instance.
        
        Returns:
            Connector instance or None if not found/connected
        """
        return self._instances.get(name)
    
    def get_connector_for_primitive(self, primitive: str) -> Optional[BaseConnector]:
        """
        Get the preferred connector for a primitive.
        
        Returns:
            Connector instance or None if none available
        """
        connector_name = self.get_preferred_connector(primitive)
        if connector_name:
            return self.get_connector(connector_name)
        return None
    
    # ========================================================================
    # Health & Status
    # ========================================================================
    
    async def check_health(self, connector_name: str) -> ConnectorHealth:
        """
        Check health of a connector.
        
        Performs an actual API call to verify connectivity.
        """
        if connector_name not in self._instances:
            return ConnectorHealth(
                status=ConnectionStatus.DISCONNECTED,
                last_check=datetime.utcnow(),
            )
        
        try:
            connector = self._instances[connector_name]
            health = await connector.check_health()
            self._status[connector_name] = health
            return health
            
        except Exception as e:
            health = ConnectorHealth(
                status=ConnectionStatus.ERROR,
                last_check=datetime.utcnow(),
                error_message=str(e),
            )
            self._status[connector_name] = health
            return health
    
    async def check_all_health(self) -> Dict[str, ConnectorHealth]:
        """Check health of all connected connectors."""
        results = {}
        
        for name in self._instances:
            results[name] = await self.check_health(name)
        
        return results
    
    def get_status(self, connector_name: str) -> Optional[ConnectorHealth]:
        """Get cached status for a connector."""
        return self._status.get(connector_name)
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get overall connection status summary."""
        total = len(self._connectors)
        connected = sum(1 for s in self._status.values() if s.status == ConnectionStatus.CONNECTED)
        
        by_provider = {}
        for provider, connectors in self._provider_map.items():
            provider_connected = any(
                self._status.get(c, ConnectorHealth(ConnectionStatus.DISCONNECTED, datetime.utcnow())).status 
                == ConnectionStatus.CONNECTED 
                for c in connectors
            )
            by_provider[provider] = {
                "connected": provider_connected,
                "connectors": connectors,
            }
        
        return {
            "total_connectors": total,
            "connected_count": connected,
            "providers": by_provider,
            "status": {
                name: {
                    "status": health.status.value,
                    "last_check": health.last_check.isoformat(),
                    "error": health.error_message,
                }
                for name, health in self._status.items()
            },
        }
    
    # ========================================================================
    # Setup Helpers
    # ========================================================================
    
    def get_setup_status(self) -> Dict[str, Any]:
        """
        Get setup status for all connectors.
        
        Returns which connectors are ready, which need setup.
        """
        ready = []
        needs_credentials = []
        needs_oauth = []
        
        for name, metadata in self._connectors.items():
            has_client = self._credential_store.has(f"{metadata.provider}:client") or not metadata.requires_client_creds
            has_token = self._credential_store.has_valid(metadata.provider)
            
            if has_token:
                ready.append(name)
            elif has_client:
                needs_oauth.append(name)
            else:
                needs_credentials.append(name)
        
        return {
            "ready": ready,
            "needs_oauth": needs_oauth,
            "needs_credentials": needs_credentials,
            "setup_urls": {
                name: self._connectors[name].setup_url
                for name in needs_credentials
            },
        }
    
    def get_setup_instructions(self, provider: str) -> str:
        """Get setup instructions for a provider."""
        connectors = self.get_connectors_for_provider(provider)
        if not connectors:
            return f"Unknown provider: {provider}"
        
        metadata = self.get_metadata(connectors[0])
        
        instructions = {
            "google": """
Google API Setup:
1. Go to https://console.cloud.google.com/
2. Create a new project
3. Enable APIs: Gmail, Calendar, Drive, People
4. Go to Credentials → Create OAuth 2.0 Client
5. Set application type to "Desktop app"
6. Download credentials JSON
7. Run: telic setup google --credentials path/to/credentials.json
""",
            "microsoft": """
Microsoft 365 Setup:
1. Go to https://portal.azure.com/
2. Navigate to Azure Active Directory → App registrations
3. Create new registration
4. Add redirect URI: http://localhost:8400/callback
5. Generate client secret
6. Set environment variables:
   AZURE_CLIENT_ID=your-client-id
   AZURE_TENANT_ID=your-tenant-id
   AZURE_CLIENT_SECRET=your-client-secret
7. Run: telic setup microsoft
""",
            "slack": """
Slack Setup:
1. Go to https://api.slack.com/apps
2. Create new app
3. Add OAuth scopes: chat:write, channels:read
4. Install to workspace
5. Copy Bot User OAuth Token
6. Run: telic setup slack --token your-token
""",
            "github": """
GitHub Setup:
1. Go to https://github.com/settings/tokens
2. Generate new token (classic)
3. Select scopes: repo, read:user
4. Run: telic setup github --token your-token
""",
        }
        
        return instructions.get(provider, f"Visit {metadata.setup_url if metadata else 'provider website'} for setup instructions.")


# Singleton instance
_registry: Optional[ConnectorRegistry] = None


def get_registry(credential_store: Optional[CredentialStore] = None) -> ConnectorRegistry:
    """
    Get or create the singleton ConnectorRegistry.
    
    Args:
        credential_store: Optional custom credential store
    
    Returns:
        ConnectorRegistry instance
    """
    global _registry
    
    if _registry is None:
        _registry = ConnectorRegistry(credential_store)
    
    return _registry


def reset_registry():
    """Reset the singleton (for testing)."""
    global _registry
    _registry = None
