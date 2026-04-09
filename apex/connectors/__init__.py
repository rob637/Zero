"""
Telic Connectors - Cloud Service Integration

Provides real API connectors for:

Google Suite:
- Gmail (send, read, search emails)
- Google Calendar (events, scheduling)
- Google Drive (files, folders)
- Google Contacts (people)

Microsoft 365:
- Outlook (send, read, search emails)
- Outlook Calendar (events, scheduling)
- OneDrive (files, folders)
- Microsoft To-Do (tasks)

Unified Abstraction:
- Provider-agnostic interface
- Same code works with Google or Microsoft
- Automatic provider detection

Setup (Google):
    1. Create Google Cloud project
    2. Enable Gmail, Calendar, Drive, People APIs
    3. Create OAuth 2.0 credentials
    4. Save credentials.json to ~/.apex/google_credentials.json

Setup (Microsoft):
    1. Create Azure AD app at https://portal.azure.com
    2. Set environment variables:
       AZURE_CLIENT_ID=your-client-id
       AZURE_TENANT_ID=your-tenant-id

Usage:
    # Unified services (recommended)
    from apex.connectors import UnifiedServices
    
    services = UnifiedServices()
    await services.connect()
    
    # Works with Gmail or Outlook
    await services.email.send(to=["bob@example.com"], ...)
    
    # Direct Google access
    from apex.connectors import GmailConnector
    gmail = GmailConnector()
    await gmail.connect()
    
    # Direct Microsoft access
    from apex.connectors import OutlookConnector
    outlook = OutlookConnector()
    await outlook.connect()
"""

# Google connectors
from .google_auth import GoogleAuth, get_google_auth, SCOPES
from .gmail import GmailConnector, Email
from .calendar import CalendarConnector, CalendarEvent
from .drive import DriveConnector, DriveFile
from .contacts import ContactsConnector, Contact

# Microsoft connectors
from .microsoft_auth import MicrosoftAuth, get_microsoft_auth
from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError
from .outlook import OutlookConnector, OutlookEmail
from .outlook_calendar import OutlookCalendarConnector, CalendarEvent as OutlookCalendarEvent
from .onedrive import OneDriveConnector, DriveItem
from .microsoft_todo import MicrosoftTodoConnector, TodoTask, TodoList
from .microsoft_excel import ExcelConnector, Workbook, Worksheet
from .microsoft_powerpoint import PowerPointConnector, Presentation as PowerPointPresentation
from .microsoft_contacts import MicrosoftContactsConnector, MicrosoftContact

# Unified services
from .unified import (
    UnifiedServices,
    Provider,
    get_unified_services,
    EmailService,
    CalendarService,
    FileService,
    TaskService,
)

# Workplace communication
from .slack import SlackConnector, SlackUser, SlackChannel, SlackMessage, create_slack_connector
from .teams import TeamsConnector, TeamsMessage, TeamsChannel
from .discord import DiscordConnector, DiscordMessage, DiscordChannel
from .twilio_sms import TwilioSMSConnector, SMSMessage

# Task management
from .todoist import TodoistConnector, TodoistTask, TodoistProject

# Cloud storage
from .dropbox import DropboxConnector, DropboxFile

# Media services
from .spotify import SpotifyConnector, SpotifyTrack
from .youtube import YouTubeConnector, YouTubeVideo

# Web search
from .web_search import WebSearchConnector, SearchResult

# Core infrastructure
from .credentials import (
    CredentialStore,
    CredentialBackend,
    EncryptedFileBackend,
    MemoryBackend,
    StoredCredential,
    CredentialType,
    get_credential_store,
    reset_credential_store,
)
from .registry import (
    ConnectorRegistry,
    ConnectorMetadata,
    ConnectionStatus,
    ConnectorHealth,
    BaseConnector,
    get_registry,
    reset_registry,
)
from .oauth_flow import (
    OAuthFlow,
    OAuthProviderConfig,
    PendingAuth,
    OAUTH_PROVIDERS,
    get_oauth_flow,
    reset_oauth_flow,
)
from .resolver import (
    PrimitiveResolver,
    ExecutionMode,
    AggregationStrategy,
    ProviderResult,
    ResolverResult,
    get_resolver,
    reset_resolver,
)

# Linear
from .linear import LinearConnector

# Desktop notifications
from .desktop_notify import DesktopNotifyConnector

__all__ = [
    # Google Auth
    'GoogleAuth',
    'get_google_auth',
    'SCOPES',
    # Gmail
    'GmailConnector',
    'Email',
    # Google Calendar
    'CalendarConnector',
    'CalendarEvent',
    # Google Drive
    'DriveConnector',
    'DriveFile',
    # Google Contacts
    'ContactsConnector',
    'Contact',
    # Microsoft Auth
    'MicrosoftAuth',
    'get_microsoft_auth',
    # Microsoft Graph
    'GraphClient',
    'get_graph_client',
    'GraphAPIError',
    # Outlook
    'OutlookConnector',
    'OutlookEmail',
    # Outlook Calendar
    'OutlookCalendarConnector',
    'OutlookCalendarEvent',
    # OneDrive
    'OneDriveConnector',
    'DriveItem',
    # Microsoft To-Do
    'MicrosoftTodoConnector',
    'TodoTask',
    'TodoList',
    # Unified Services
    'UnifiedServices',
    'Provider',
    'get_unified_services',
    'EmailService',
    'CalendarService',
    'FileService',
    'TaskService',
    # Slack
    'SlackConnector',
    'SlackUser',
    'SlackChannel',
    'SlackMessage',
    'create_slack_connector',
    # Teams
    'TeamsConnector',
    'TeamsMessage',
    'TeamsChannel',
    # Discord
    'DiscordConnector',
    'DiscordMessage',
    'DiscordChannel',
    # Twilio SMS
    'TwilioSMSConnector',
    'SMSMessage',
    # Todoist
    'TodoistConnector',
    'TodoistTask',
    'TodoistProject',
    # Dropbox
    'DropboxConnector',
    'DropboxFile',
    # Spotify
    'SpotifyConnector',
    'SpotifyTrack',
    # YouTube
    'YouTubeConnector',
    'YouTubeVideo',
    # Web Search
    'WebSearchConnector',
    'SearchResult',
    # Weather
    'WeatherConnector',
    'WeatherData',
    # News
    'NewsConnector',
    'Article',
    # Notion
    'NotionConnector',
    # Linear
    'LinearConnector',
    # Desktop Notifications
    'DesktopNotifyConnector',
    # OAuth Flow
    'OAuthFlow',
    'OAuthProviderConfig',
    'PendingAuth',
    'OAUTH_PROVIDERS',
    'get_oauth_flow',
    'reset_oauth_flow',
    # Primitive Resolver
    'PrimitiveResolver',
    'ExecutionMode',
    'AggregationStrategy',
    'ProviderResult',
    'ResolverResult',
    'get_resolver',
    'reset_resolver',
]

