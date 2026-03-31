"""
Service Adapters - Connecting the Brain to the World

These adapters bridge the World Interface to actual service connectors.

Each adapter translates between the brain's abstract actions
and the concrete APIs of external services.

Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                        BRAIN                                    │
    │                          │                                      │
    │                    World Interface                              │
    │                          │                                      │
    │              ┌───────────┼───────────┐                         │
    │              │           │           │                         │
    │           Gmail       Calendar     Drive      ... Adapters     │
    │           Adapter      Adapter    Adapter                      │
    │              │           │           │                         │
    │           Gmail       Calendar     Drive      ... Connectors   │
    │         Connector    Connector   Connector                     │
    │              │           │           │                         │
    │              └───────────┴───────────┘                         │
    │                          │                                      │
    │                   External APIs                                 │
    └─────────────────────────────────────────────────────────────────┘
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceType(Enum):
    """Types of services."""
    EMAIL = "email"
    CALENDAR = "calendar"
    FILES = "files"
    TASKS = "tasks"
    NOTES = "notes"
    BROWSER = "browser"
    SYSTEM = "system"


class ActionResult(Enum):
    """Result of an action."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"


@dataclass
class AdapterResult:
    """Result from adapter action."""
    success: bool
    result: ActionResult
    data: Any = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ServiceAdapter(ABC):
    """
    Base class for service adapters.
    
    Each adapter must implement:
    - execute() - perform an action
    - observe() - get observations from the service
    - get_capabilities() - what can this adapter do
    """
    
    def __init__(self, connector):
        self._connector = connector
        self._initialized = False
    
    @property
    @abstractmethod
    def service_type(self) -> ServiceType:
        """What type of service this adapter provides."""
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        """What actions this adapter can perform."""
        pass
    
    @abstractmethod
    async def execute(self, action: str, parameters: Dict[str, Any]) -> AdapterResult:
        """Execute an action on the service."""
        pass
    
    @abstractmethod
    async def observe(self) -> List[Dict[str, Any]]:
        """Get observations/updates from the service."""
        pass
    
    async def initialize(self) -> bool:
        """Initialize the adapter."""
        self._initialized = True
        return True
    
    @property
    def is_available(self) -> bool:
        """Check if adapter is available."""
        return self._initialized


# === Email Adapter (Gmail) ===

class GmailAdapter(ServiceAdapter):
    """
    Adapter for Gmail service.
    
    Enables the brain to:
    - Read and search emails
    - Send emails
    - Manage labels
    - Detect important messages
    """
    
    @property
    def service_type(self) -> ServiceType:
        return ServiceType.EMAIL
    
    @property
    def capabilities(self) -> List[str]:
        return [
            "list_emails",
            "read_email",
            "search_emails",
            "send_email",
            "draft_email",
            "archive_email",
            "label_email",
            "get_unread_count",
            "get_important",
        ]
    
    async def execute(self, action: str, parameters: Dict[str, Any]) -> AdapterResult:
        """Execute Gmail action."""
        try:
            if action == "list_emails":
                emails = await self._connector.list_messages(
                    max_results=parameters.get("limit", 20),
                    query=parameters.get("query", ""),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=emails,
                    metadata={"count": len(emails)},
                )
            
            elif action == "read_email":
                email_id = parameters.get("email_id")
                if not email_id:
                    return AdapterResult(
                        success=False,
                        result=ActionResult.FAILED,
                        error="email_id required",
                    )
                
                email = await self._connector.get_message(email_id)
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=email,
                )
            
            elif action == "search_emails":
                query = parameters.get("query", "")
                emails = await self._connector.list_messages(
                    max_results=parameters.get("limit", 20),
                    query=query,
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=emails,
                    metadata={"query": query, "count": len(emails)},
                )
            
            elif action == "send_email":
                result = await self._connector.send_message(
                    to=parameters.get("to"),
                    subject=parameters.get("subject"),
                    body=parameters.get("body"),
                    cc=parameters.get("cc"),
                    bcc=parameters.get("bcc"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=result,
                )
            
            elif action == "draft_email":
                result = await self._connector.create_draft(
                    to=parameters.get("to"),
                    subject=parameters.get("subject"),
                    body=parameters.get("body"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=result,
                )
            
            elif action == "get_unread_count":
                emails = await self._connector.list_messages(
                    max_results=100,
                    query="is:unread",
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data={"unread_count": len(emails)},
                )
            
            elif action == "get_important":
                emails = await self._connector.list_messages(
                    max_results=10,
                    query="is:important is:unread",
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=emails,
                    metadata={"count": len(emails)},
                )
            
            else:
                return AdapterResult(
                    success=False,
                    result=ActionResult.FAILED,
                    error=f"Unknown action: {action}",
                )
                
        except Exception as e:
            logger.error(f"Gmail adapter error: {e}")
            return AdapterResult(
                success=False,
                result=ActionResult.FAILED,
                error=str(e),
            )
    
    async def observe(self) -> List[Dict[str, Any]]:
        """Get email observations."""
        observations = []
        
        try:
            # Check for new unread emails
            unread = await self._connector.list_messages(
                max_results=5,
                query="is:unread",
            )
            
            if unread:
                observations.append({
                    "type": "unread_emails",
                    "count": len(unread),
                    "preview": [
                        {
                            "from": e.get("from", ""),
                            "subject": e.get("subject", ""),
                        }
                        for e in unread[:3]
                    ],
                    "importance": 0.6 if len(unread) > 5 else 0.4,
                    "urgency": 0.5,
                })
            
            # Check for important emails
            important = await self._connector.list_messages(
                max_results=3,
                query="is:important is:unread",
            )
            
            if important:
                observations.append({
                    "type": "important_emails",
                    "count": len(important),
                    "emails": important,
                    "importance": 0.8,
                    "urgency": 0.7,
                })
                
        except Exception as e:
            logger.error(f"Gmail observation error: {e}")
        
        return observations


# === Calendar Adapter ===

class CalendarAdapter(ServiceAdapter):
    """
    Adapter for Google Calendar service.
    
    Enables the brain to:
    - View upcoming events
    - Create events
    - Handle conflicts
    - Anticipate schedule
    """
    
    @property
    def service_type(self) -> ServiceType:
        return ServiceType.CALENDAR
    
    @property
    def capabilities(self) -> List[str]:
        return [
            "list_events",
            "get_event",
            "create_event",
            "update_event",
            "delete_event",
            "get_free_busy",
            "get_upcoming",
            "find_conflicts",
        ]
    
    async def execute(self, action: str, parameters: Dict[str, Any]) -> AdapterResult:
        """Execute calendar action."""
        try:
            if action == "list_events":
                events = await self._connector.list_events(
                    time_min=parameters.get("start"),
                    time_max=parameters.get("end"),
                    max_results=parameters.get("limit", 10),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=events,
                    metadata={"count": len(events)},
                )
            
            elif action == "get_upcoming":
                # Next 24 hours
                now = datetime.utcnow()
                tomorrow = now + timedelta(days=1)
                
                events = await self._connector.list_events(
                    time_min=now.isoformat() + "Z",
                    time_max=tomorrow.isoformat() + "Z",
                    max_results=20,
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=events,
                    metadata={"timeframe": "24h"},
                )
            
            elif action == "create_event":
                event = await self._connector.create_event(
                    summary=parameters.get("title"),
                    start_time=parameters.get("start"),
                    end_time=parameters.get("end"),
                    description=parameters.get("description"),
                    location=parameters.get("location"),
                    attendees=parameters.get("attendees"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=event,
                )
            
            elif action == "update_event":
                event = await self._connector.update_event(
                    event_id=parameters.get("event_id"),
                    summary=parameters.get("title"),
                    start_time=parameters.get("start"),
                    end_time=parameters.get("end"),
                    description=parameters.get("description"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=event,
                )
            
            elif action == "delete_event":
                await self._connector.delete_event(parameters.get("event_id"))
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                )
            
            elif action == "get_free_busy":
                # Get busy times for finding free slots
                now = datetime.utcnow()
                end = now + timedelta(days=parameters.get("days", 7))
                
                events = await self._connector.list_events(
                    time_min=now.isoformat() + "Z",
                    time_max=end.isoformat() + "Z",
                    max_results=50,
                )
                
                busy_times = [
                    {
                        "start": e.get("start", {}).get("dateTime"),
                        "end": e.get("end", {}).get("dateTime"),
                        "summary": e.get("summary", "Busy"),
                    }
                    for e in events
                ]
                
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data={"busy": busy_times},
                )
            
            else:
                return AdapterResult(
                    success=False,
                    result=ActionResult.FAILED,
                    error=f"Unknown action: {action}",
                )
                
        except Exception as e:
            logger.error(f"Calendar adapter error: {e}")
            return AdapterResult(
                success=False,
                result=ActionResult.FAILED,
                error=str(e),
            )
    
    async def observe(self) -> List[Dict[str, Any]]:
        """Get calendar observations."""
        observations = []
        
        try:
            now = datetime.utcnow()
            
            # Upcoming events in next 2 hours
            soon = now + timedelta(hours=2)
            events = await self._connector.list_events(
                time_min=now.isoformat() + "Z",
                time_max=soon.isoformat() + "Z",
                max_results=5,
            )
            
            if events:
                observations.append({
                    "type": "upcoming_events",
                    "count": len(events),
                    "events": events,
                    "importance": 0.7,
                    "urgency": 0.6,
                })
            
            # Today's schedule overview
            end_of_day = now.replace(hour=23, minute=59, second=59)
            today_events = await self._connector.list_events(
                time_min=now.isoformat() + "Z",
                time_max=end_of_day.isoformat() + "Z",
                max_results=10,
            )
            
            if today_events:
                observations.append({
                    "type": "today_schedule",
                    "count": len(today_events),
                    "next": today_events[0] if today_events else None,
                    "importance": 0.5,
                    "urgency": 0.3,
                })
                
        except Exception as e:
            logger.error(f"Calendar observation error: {e}")
        
        return observations


# === Drive Adapter ===

class DriveAdapter(ServiceAdapter):
    """
    Adapter for Google Drive service.
    
    Enables the brain to:
    - Browse files
    - Search content
    - Read documents
    - Upload/create files
    """
    
    @property
    def service_type(self) -> ServiceType:
        return ServiceType.FILES
    
    @property
    def capabilities(self) -> List[str]:
        return [
            "list_files",
            "search_files",
            "get_file",
            "read_file",
            "upload_file",
            "create_document",
            "download_file",
            "get_recent",
            "get_shared",
        ]
    
    async def execute(self, action: str, parameters: Dict[str, Any]) -> AdapterResult:
        """Execute Drive action."""
        try:
            if action == "list_files":
                files = await self._connector.list_files(
                    folder_id=parameters.get("folder_id"),
                    page_size=parameters.get("limit", 20),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=files,
                    metadata={"count": len(files)},
                )
            
            elif action == "search_files":
                files = await self._connector.search_files(
                    query=parameters.get("query"),
                    page_size=parameters.get("limit", 10),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=files,
                    metadata={"query": parameters.get("query"), "count": len(files)},
                )
            
            elif action == "get_file":
                metadata = await self._connector.get_file_metadata(
                    file_id=parameters.get("file_id"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=metadata,
                )
            
            elif action == "read_file":
                content = await self._connector.download_file(
                    file_id=parameters.get("file_id"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data={"content": content.decode() if isinstance(content, bytes) else content},
                )
            
            elif action == "upload_file":
                result = await self._connector.upload_file(
                    file_path=parameters.get("path"),
                    folder_id=parameters.get("folder_id"),
                    mime_type=parameters.get("mime_type"),
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=result,
                )
            
            elif action == "get_recent":
                files = await self._connector.list_files(
                    page_size=10,
                )
                return AdapterResult(
                    success=True,
                    result=ActionResult.SUCCESS,
                    data=files,
                )
            
            else:
                return AdapterResult(
                    success=False,
                    result=ActionResult.FAILED,
                    error=f"Unknown action: {action}",
                )
                
        except Exception as e:
            logger.error(f"Drive adapter error: {e}")
            return AdapterResult(
                success=False,
                result=ActionResult.FAILED,
                error=str(e),
            )
    
    async def observe(self) -> List[Dict[str, Any]]:
        """Get Drive observations."""
        observations = []
        
        try:
            # Recent files
            recent = await self._connector.list_files(page_size=5)
            
            if recent:
                observations.append({
                    "type": "recent_files",
                    "count": len(recent),
                    "files": recent,
                    "importance": 0.3,
                    "urgency": 0.1,
                })
                
        except Exception as e:
            logger.error(f"Drive observation error: {e}")
        
        return observations


# === Adapter Registry ===

class AdapterRegistry:
    """
    Registry for managing service adapters.
    
    Provides discovery and instantiation of adapters.
    """
    
    def __init__(self):
        self._adapters: Dict[ServiceType, ServiceAdapter] = {}
        self._connector_map: Dict[str, type] = {
            "gmail": GmailAdapter,
            "calendar": CalendarAdapter,
            "drive": DriveAdapter,
        }
    
    def register(self, adapter: ServiceAdapter):
        """Register an adapter."""
        self._adapters[adapter.service_type] = adapter
        logger.info(f"Registered adapter: {adapter.service_type.value}")
    
    def get(self, service_type: ServiceType) -> Optional[ServiceAdapter]:
        """Get adapter by service type."""
        return self._adapters.get(service_type)
    
    def get_all(self) -> List[ServiceAdapter]:
        """Get all registered adapters."""
        return list(self._adapters.values())
    
    def create_adapter(self, service_name: str, connector) -> Optional[ServiceAdapter]:
        """Create and register adapter for a service."""
        adapter_class = self._connector_map.get(service_name)
        if adapter_class:
            adapter = adapter_class(connector)
            self.register(adapter)
            return adapter
        return None
    
    def get_capabilities(self) -> Dict[str, List[str]]:
        """Get all capabilities from all adapters."""
        return {
            adapter.service_type.value: adapter.capabilities
            for adapter in self._adapters.values()
        }
