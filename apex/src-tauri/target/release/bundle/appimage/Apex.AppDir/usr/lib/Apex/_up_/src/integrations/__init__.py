"""
Apex Integration Platform
=========================

This module contains the core integration infrastructure:
- Credential management (OAuth, API keys)
- Event bus for cross-service communication
- Context engine for AI reasoning
- Service connectors
"""

from .credential_manager import (
    CredentialManager,
    OAuth2Credentials,
    APIKeyCredentials,
    get_credential_manager,
    OAUTH_PROVIDERS,
)
from .event_bus import (
    EventBus,
    Event,
    EventHandler,
    EventPriority,
    get_event_bus,
    GmailEvents,
    CalendarEvents,
    DriveEvents,
    LocalEvents,
)
from .context_engine import (
    ContextEngine,
    Entity,
    EntityType,
    TemporalContext,
    RelationshipType,
    get_context_engine,
)

__all__ = [
    # Credential Manager
    "CredentialManager",
    "OAuth2Credentials",
    "APIKeyCredentials",
    "get_credential_manager",
    "OAUTH_PROVIDERS",
    # Event Bus
    "EventBus",
    "Event",
    "EventHandler",
    "EventPriority",
    "get_event_bus",
    "GmailEvents",
    "CalendarEvents",
    "DriveEvents",
    "LocalEvents",
    # Context Engine
    "ContextEngine",
    "Entity",
    "EntityType",
    "TemporalContext",
    "RelationshipType",
    "get_context_engine",
]
