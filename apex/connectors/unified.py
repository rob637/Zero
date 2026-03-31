"""
Unified Service Abstraction Layer

Provider-agnostic interface for email, calendar, files, and tasks.
Automatically routes to Google or Microsoft based on user's connected accounts.

Key principle: Write once, run anywhere.
- Same code works with Gmail or Outlook
- Same code works with Google Calendar or Outlook Calendar
- Same code works with Google Drive or OneDrive
- Same code works with Google Tasks or Microsoft To-Do

Usage:
    from connectors.unified import UnifiedServices
    
    services = UnifiedServices()
    await services.connect()  # Connects to all available providers
    
    # Send email - works with Gmail or Outlook
    await services.email.send(
        to=["bob@example.com"],
        subject="Hello",
        body="Hi Bob!",
    )
    
    # Create calendar event - works with Google or Outlook
    await services.calendar.create_event(
        title="Team Meeting",
        start=datetime.now(),
        end=datetime.now() + timedelta(hours=1),
    )
    
    # Upload file - works with Drive or OneDrive
    await services.files.upload("local.pdf", "/Documents/remote.pdf")
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Union

import logging
logger = logging.getLogger(__name__)


class Provider(Enum):
    """Service providers."""
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    LOCAL = "local"  # For file operations without cloud


# ============================================================================
# Abstract Interfaces
# ============================================================================

class EmailService(ABC):
    """Abstract email service interface."""
    
    @property
    @abstractmethod
    def provider(self) -> Provider:
        pass
    
    @abstractmethod
    async def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: List[str] = None,
        bcc: List[str] = None,
        html: bool = False,
        attachments: List[str] = None,
    ) -> Dict:
        """Send an email."""
        pass
    
    @abstractmethod
    async def list_messages(
        self,
        max_results: int = 25,
        folder: str = "inbox",
        unread_only: bool = False,
    ) -> List[Dict]:
        """List recent messages."""
        pass
    
    @abstractmethod
    async def search(self, query: str, max_results: int = 25) -> List[Dict]:
        """Search messages."""
        pass
    
    @abstractmethod
    async def get_message(self, message_id: str) -> Dict:
        """Get full message content."""
        pass
    
    @abstractmethod
    async def mark_read(self, message_id: str) -> bool:
        """Mark message as read."""
        pass


class CalendarService(ABC):
    """Abstract calendar service interface."""
    
    @property
    @abstractmethod
    def provider(self) -> Provider:
        pass
    
    @abstractmethod
    async def list_events(
        self,
        start_time: datetime = None,
        end_time: datetime = None,
        max_results: int = 50,
    ) -> List[Dict]:
        """List calendar events."""
        pass
    
    @abstractmethod
    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        location: str = None,
        description: str = None,
        attendees: List[str] = None,
        reminder_minutes: int = 15,
    ) -> Dict:
        """Create a calendar event."""
        pass
    
    @abstractmethod
    async def update_event(
        self,
        event_id: str,
        title: str = None,
        start: datetime = None,
        end: datetime = None,
        location: str = None,
        description: str = None,
    ) -> Dict:
        """Update an event."""
        pass
    
    @abstractmethod
    async def delete_event(self, event_id: str) -> bool:
        """Delete an event."""
        pass
    
    @abstractmethod
    async def find_free_time(
        self,
        attendees: List[str],
        duration_minutes: int = 60,
        start_time: datetime = None,
        end_time: datetime = None,
    ) -> List[Dict]:
        """Find available meeting times."""
        pass


class FileService(ABC):
    """Abstract cloud file service interface."""
    
    @property
    @abstractmethod
    def provider(self) -> Provider:
        pass
    
    @abstractmethod
    async def list_items(self, path: str = "/", max_results: int = 100) -> List[Dict]:
        """List files and folders."""
        pass
    
    @abstractmethod
    async def search(self, query: str, max_results: int = 50) -> List[Dict]:
        """Search files."""
        pass
    
    @abstractmethod
    async def download(self, path: str) -> bytes:
        """Download file content."""
        pass
    
    @abstractmethod
    async def upload(
        self,
        local_path: str,
        remote_path: str,
    ) -> Dict:
        """Upload a file."""
        pass
    
    @abstractmethod
    async def create_folder(self, path: str, name: str) -> Dict:
        """Create a folder."""
        pass
    
    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete a file or folder."""
        pass
    
    @abstractmethod
    async def share(
        self,
        path: str,
        anyone_can_view: bool = True,
    ) -> Dict:
        """Create a sharing link."""
        pass


class TaskService(ABC):
    """Abstract task/todo service interface."""
    
    @property
    @abstractmethod
    def provider(self) -> Provider:
        pass
    
    @abstractmethod
    async def list_tasks(
        self,
        list_id: str = None,
        include_completed: bool = False,
    ) -> List[Dict]:
        """List tasks."""
        pass
    
    @abstractmethod
    async def create_task(
        self,
        title: str,
        due_date: date = None,
        notes: str = None,
        importance: str = "normal",
    ) -> Dict:
        """Create a task."""
        pass
    
    @abstractmethod
    async def complete_task(self, task_id: str) -> Dict:
        """Mark task as complete."""
        pass
    
    @abstractmethod
    async def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        pass


# ============================================================================
# Google Implementations
# ============================================================================

class GoogleEmailService(EmailService):
    """Gmail implementation of EmailService."""
    
    def __init__(self):
        from .gmail import GmailConnector
        self._gmail = GmailConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.GOOGLE
    
    async def connect(self) -> bool:
        self._connected = await self._gmail.connect()
        return self._connected
    
    async def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: List[str] = None,
        bcc: List[str] = None,
        html: bool = False,
        attachments: List[str] = None,
    ) -> Dict:
        result = await self._gmail.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            html=html,
            attachments=attachments,
        )
        return result
    
    async def list_messages(
        self,
        max_results: int = 25,
        folder: str = "inbox",
        unread_only: bool = False,
    ) -> List[Dict]:
        query = f"in:{folder}"
        if unread_only:
            query += " is:unread"
        
        messages = await self._gmail.list_messages(query=query, max_results=max_results)
        return [m.to_dict() for m in messages]
    
    async def search(self, query: str, max_results: int = 25) -> List[Dict]:
        messages = await self._gmail.search(query=query, max_results=max_results)
        return [m.to_dict() for m in messages]
    
    async def get_message(self, message_id: str) -> Dict:
        msg = await self._gmail.get_message(message_id)
        return msg.to_dict()
    
    async def mark_read(self, message_id: str) -> bool:
        return await self._gmail.mark_read(message_id)


class GoogleCalendarService(CalendarService):
    """Google Calendar implementation."""
    
    def __init__(self):
        from .calendar import CalendarConnector
        self._calendar = CalendarConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.GOOGLE
    
    async def connect(self) -> bool:
        self._connected = await self._calendar.connect()
        return self._connected
    
    async def list_events(
        self,
        start_time: datetime = None,
        end_time: datetime = None,
        max_results: int = 50,
    ) -> List[Dict]:
        events = await self._calendar.list_events(
            start_time=start_time,
            end_time=end_time,
            max_results=max_results,
        )
        return [e.to_dict() for e in events]
    
    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        location: str = None,
        description: str = None,
        attendees: List[str] = None,
        reminder_minutes: int = 15,
    ) -> Dict:
        event = await self._calendar.create_event(
            summary=title,
            start_time=start,
            end_time=end,
            location=location,
            description=description,
            attendees=attendees,
        )
        return event.to_dict()
    
    async def update_event(
        self,
        event_id: str,
        title: str = None,
        start: datetime = None,
        end: datetime = None,
        location: str = None,
        description: str = None,
    ) -> Dict:
        event = await self._calendar.update_event(
            event_id=event_id,
            summary=title,
            start_time=start,
            end_time=end,
            location=location,
            description=description,
        )
        return event.to_dict()
    
    async def delete_event(self, event_id: str) -> bool:
        return await self._calendar.delete_event(event_id)
    
    async def find_free_time(
        self,
        attendees: List[str],
        duration_minutes: int = 60,
        start_time: datetime = None,
        end_time: datetime = None,
    ) -> List[Dict]:
        # Google Calendar doesn't have a direct "find free time" API
        # We'd need to query freebusy and compute available slots
        # For now, return empty - can be enhanced
        return []


class GoogleDriveService(FileService):
    """Google Drive implementation."""
    
    def __init__(self):
        from .drive import DriveConnector
        self._drive = DriveConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.GOOGLE
    
    async def connect(self) -> bool:
        self._connected = await self._drive.connect()
        return self._connected
    
    async def list_items(self, path: str = "/", max_results: int = 100) -> List[Dict]:
        items = await self._drive.list_files(
            folder_id="root" if path == "/" else None,
            max_results=max_results,
        )
        return [i.to_dict() for i in items]
    
    async def search(self, query: str, max_results: int = 50) -> List[Dict]:
        items = await self._drive.search(query=query, max_results=max_results)
        return [i.to_dict() for i in items]
    
    async def download(self, path: str) -> bytes:
        # For Drive, path should be file_id
        return await self._drive.download_file(file_id=path)
    
    async def upload(self, local_path: str, remote_path: str) -> Dict:
        name = Path(remote_path).name
        item = await self._drive.upload_file(local_path=local_path, name=name)
        return item.to_dict()
    
    async def create_folder(self, path: str, name: str) -> Dict:
        item = await self._drive.create_folder(name=name)
        return item.to_dict()
    
    async def delete(self, path: str) -> bool:
        return await self._drive.delete_file(file_id=path)
    
    async def share(self, path: str, anyone_can_view: bool = True) -> Dict:
        result = await self._drive.share_file(
            file_id=path,
            role="reader" if anyone_can_view else "writer",
        )
        return result


# ============================================================================
# Microsoft Implementations
# ============================================================================

class MicrosoftEmailService(EmailService):
    """Outlook implementation of EmailService."""
    
    def __init__(self):
        from .outlook import OutlookConnector
        self._outlook = OutlookConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.MICROSOFT
    
    async def connect(self) -> bool:
        self._connected = await self._outlook.connect()
        return self._connected
    
    async def send(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: List[str] = None,
        bcc: List[str] = None,
        html: bool = False,
        attachments: List[str] = None,
    ) -> Dict:
        return await self._outlook.send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            bcc=bcc,
            html=html,
            attachments=attachments,
        )
    
    async def list_messages(
        self,
        max_results: int = 25,
        folder: str = "inbox",
        unread_only: bool = False,
    ) -> List[Dict]:
        messages = await self._outlook.list_messages(
            folder=folder,
            max_results=max_results,
            unread_only=unread_only,
        )
        return [m.to_dict() for m in messages]
    
    async def search(self, query: str, max_results: int = 25) -> List[Dict]:
        messages = await self._outlook.search(query=query, max_results=max_results)
        return [m.to_dict() for m in messages]
    
    async def get_message(self, message_id: str) -> Dict:
        msg = await self._outlook.get_message(message_id)
        return msg.to_dict()
    
    async def mark_read(self, message_id: str) -> bool:
        return await self._outlook.mark_read(message_id)


class MicrosoftCalendarService(CalendarService):
    """Outlook Calendar implementation."""
    
    def __init__(self):
        from .outlook_calendar import OutlookCalendarConnector
        self._calendar = OutlookCalendarConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.MICROSOFT
    
    async def connect(self) -> bool:
        self._connected = await self._calendar.connect()
        return self._connected
    
    async def list_events(
        self,
        start_time: datetime = None,
        end_time: datetime = None,
        max_results: int = 50,
    ) -> List[Dict]:
        events = await self._calendar.list_events(
            start_time=start_time,
            end_time=end_time,
            max_results=max_results,
        )
        return [e.to_dict() for e in events]
    
    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        location: str = None,
        description: str = None,
        attendees: List[str] = None,
        reminder_minutes: int = 15,
    ) -> Dict:
        event = await self._calendar.create_event(
            subject=title,
            start=start,
            end=end,
            location=location,
            description=description,
            attendees=attendees,
            reminder_minutes=reminder_minutes,
        )
        return event.to_dict()
    
    async def update_event(
        self,
        event_id: str,
        title: str = None,
        start: datetime = None,
        end: datetime = None,
        location: str = None,
        description: str = None,
    ) -> Dict:
        event = await self._calendar.update_event(
            event_id=event_id,
            subject=title,
            start=start,
            end=end,
            location=location,
            description=description,
        )
        return event.to_dict()
    
    async def delete_event(self, event_id: str) -> bool:
        return await self._calendar.delete_event(event_id)
    
    async def find_free_time(
        self,
        attendees: List[str],
        duration_minutes: int = 60,
        start_time: datetime = None,
        end_time: datetime = None,
    ) -> List[Dict]:
        return await self._calendar.find_free_time(
            attendees=attendees,
            duration_minutes=duration_minutes,
            start_time=start_time,
            end_time=end_time,
        )


class MicrosoftDriveService(FileService):
    """OneDrive implementation."""
    
    def __init__(self):
        from .onedrive import OneDriveConnector
        self._drive = OneDriveConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.MICROSOFT
    
    async def connect(self) -> bool:
        self._connected = await self._drive.connect()
        return self._connected
    
    async def list_items(self, path: str = "/", max_results: int = 100) -> List[Dict]:
        items = await self._drive.list_items(path=path, max_results=max_results)
        return [i.to_dict() for i in items]
    
    async def search(self, query: str, max_results: int = 50) -> List[Dict]:
        items = await self._drive.search(query=query, max_results=max_results)
        return [i.to_dict() for i in items]
    
    async def download(self, path: str) -> bytes:
        return await self._drive.download_file(path=path)
    
    async def upload(self, local_path: str, remote_path: str) -> Dict:
        item = await self._drive.upload_file(local_path=local_path, remote_path=remote_path)
        return item.to_dict()
    
    async def create_folder(self, path: str, name: str) -> Dict:
        item = await self._drive.create_folder(path=path, name=name)
        return item.to_dict()
    
    async def delete(self, path: str) -> bool:
        return await self._drive.delete_item(path=path)
    
    async def share(self, path: str, anyone_can_view: bool = True) -> Dict:
        return await self._drive.create_share_link(
            path=path,
            link_type="view" if anyone_can_view else "edit",
        )


class MicrosoftTaskService(TaskService):
    """Microsoft To-Do implementation."""
    
    def __init__(self):
        from .microsoft_todo import MicrosoftTodoConnector
        self._todo = MicrosoftTodoConnector()
        self._connected = False
    
    @property
    def provider(self) -> Provider:
        return Provider.MICROSOFT
    
    async def connect(self) -> bool:
        self._connected = await self._todo.connect()
        return self._connected
    
    async def list_tasks(
        self,
        list_id: str = None,
        include_completed: bool = False,
    ) -> List[Dict]:
        tasks = await self._todo.list_tasks(
            list_id=list_id,
            include_completed=include_completed,
        )
        return [t.to_dict() for t in tasks]
    
    async def create_task(
        self,
        title: str,
        due_date: date = None,
        notes: str = None,
        importance: str = "normal",
    ) -> Dict:
        task = await self._todo.create_task(
            title=title,
            due_date=due_date,
            body=notes,
            importance=importance,
        )
        return task.to_dict()
    
    async def complete_task(self, task_id: str) -> Dict:
        task = await self._todo.complete_task(task_id)
        return task.to_dict()
    
    async def delete_task(self, task_id: str) -> bool:
        return await self._todo.delete_task(task_id)


# ============================================================================
# Unified Services Container
# ============================================================================

@dataclass
class ConnectedProviders:
    """Tracks which providers are connected."""
    google: bool = False
    microsoft: bool = False
    
    @property
    def any_connected(self) -> bool:
        return self.google or self.microsoft


class UnifiedServices:
    """
    Unified interface to cloud services.
    
    Automatically discovers and uses available providers.
    Provides a single API for email, calendar, files, and tasks
    that works with Google or Microsoft.
    """
    
    def __init__(self, prefer: Provider = None):
        """
        Initialize unified services.
        
        Args:
            prefer: Preferred provider (Google or Microsoft).
                   If None, uses whichever is available (Google first).
        """
        self._prefer = prefer
        self._providers = ConnectedProviders()
        
        # Email services
        self._gmail: Optional[GoogleEmailService] = None
        self._outlook: Optional[MicrosoftEmailService] = None
        
        # Calendar services
        self._gcal: Optional[GoogleCalendarService] = None
        self._ocal: Optional[MicrosoftCalendarService] = None
        
        # File services
        self._gdrive: Optional[GoogleDriveService] = None
        self._onedrive: Optional[MicrosoftDriveService] = None
        
        # Task services
        self._mtodo: Optional[MicrosoftTaskService] = None
        # Note: Google Tasks would go here
        
        self._connected = False
    
    async def connect(
        self,
        google: bool = True,
        microsoft: bool = True,
    ) -> ConnectedProviders:
        """
        Connect to available providers.
        
        Args:
            google: Try to connect to Google
            microsoft: Try to connect to Microsoft
        
        Returns:
            ConnectedProviders showing what connected
        """
        tasks = []
        
        if google:
            tasks.append(self._connect_google())
        if microsoft:
            tasks.append(self._connect_microsoft())
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self._connected = self._providers.any_connected
        return self._providers
    
    async def _connect_google(self):
        """Try to connect to Google services."""
        connected_any = False
        
        try:
            # Email
            self._gmail = GoogleEmailService()
            if await self._gmail.connect():
                logger.info("Connected to Gmail")
                connected_any = True
            else:
                self._gmail = None
        except Exception as e:
            logger.debug(f"Could not connect to Gmail: {e}")
            self._gmail = None
        
        try:
            # Calendar
            self._gcal = GoogleCalendarService()
            if await self._gcal.connect():
                logger.info("Connected to Google Calendar")
                connected_any = True
            else:
                self._gcal = None
        except Exception as e:
            logger.debug(f"Could not connect to Google Calendar: {e}")
            self._gcal = None
        
        try:
            # Drive
            self._gdrive = GoogleDriveService()
            if await self._gdrive.connect():
                logger.info("Connected to Google Drive")
                connected_any = True
            else:
                self._gdrive = None
        except Exception as e:
            logger.debug(f"Could not connect to Google Drive: {e}")
            self._gdrive = None
        
        self._providers.google = connected_any
    
    async def _connect_microsoft(self):
        """Try to connect to Microsoft services."""
        connected_any = False
        
        try:
            # Email
            self._outlook = MicrosoftEmailService()
            if await self._outlook.connect():
                logger.info("Connected to Outlook")
                connected_any = True
            else:
                self._outlook = None
        except Exception as e:
            logger.debug(f"Could not connect to Outlook: {e}")
            self._outlook = None
        
        try:
            # Calendar
            self._ocal = MicrosoftCalendarService()
            if await self._ocal.connect():
                logger.info("Connected to Outlook Calendar")
                connected_any = True
            else:
                self._ocal = None
        except Exception as e:
            logger.debug(f"Could not connect to Outlook Calendar: {e}")
            self._ocal = None
        
        try:
            # Drive
            self._onedrive = MicrosoftDriveService()
            if await self._onedrive.connect():
                logger.info("Connected to OneDrive")
                connected_any = True
            else:
                self._onedrive = None
        except Exception as e:
            logger.debug(f"Could not connect to OneDrive: {e}")
            self._onedrive = None
        
        try:
            # Tasks
            self._mtodo = MicrosoftTaskService()
            if await self._mtodo.connect():
                logger.info("Connected to Microsoft To-Do")
                connected_any = True
            else:
                self._mtodo = None
        except Exception as e:
            logger.debug(f"Could not connect to Microsoft To-Do: {e}")
            self._mtodo = None
        
        self._providers.microsoft = connected_any
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @property
    def providers(self) -> ConnectedProviders:
        return self._providers
    
    @property
    def email(self) -> Optional[EmailService]:
        """Get email service (Gmail or Outlook)."""
        if self._prefer == Provider.MICROSOFT and self._outlook:
            return self._outlook
        if self._prefer == Provider.GOOGLE and self._gmail:
            return self._gmail
        # Default: prefer Google if available
        return self._gmail or self._outlook
    
    @property
    def calendar(self) -> Optional[CalendarService]:
        """Get calendar service (Google Calendar or Outlook Calendar)."""
        if self._prefer == Provider.MICROSOFT and self._ocal:
            return self._ocal
        if self._prefer == Provider.GOOGLE and self._gcal:
            return self._gcal
        return self._gcal or self._ocal
    
    @property
    def files(self) -> Optional[FileService]:
        """Get file service (Google Drive or OneDrive)."""
        if self._prefer == Provider.MICROSOFT and self._onedrive:
            return self._onedrive
        if self._prefer == Provider.GOOGLE and self._gdrive:
            return self._gdrive
        return self._gdrive or self._onedrive
    
    @property
    def tasks(self) -> Optional[TaskService]:
        """Get task service (currently only Microsoft To-Do)."""
        return self._mtodo
    
    # Convenience methods that auto-select provider
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        **kwargs,
    ) -> Dict:
        """Send email via available provider."""
        svc = self.email
        if not svc:
            raise RuntimeError("No email service connected")
        return await svc.send(to=to, subject=subject, body=body, **kwargs)
    
    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime,
        **kwargs,
    ) -> Dict:
        """Create calendar event via available provider."""
        svc = self.calendar
        if not svc:
            raise RuntimeError("No calendar service connected")
        return await svc.create_event(title=title, start=start, end=end, **kwargs)
    
    async def upload_file(
        self,
        local_path: str,
        remote_path: str,
    ) -> Dict:
        """Upload file via available provider."""
        svc = self.files
        if not svc:
            raise RuntimeError("No file service connected")
        return await svc.upload(local_path=local_path, remote_path=remote_path)
    
    async def create_task(
        self,
        title: str,
        due_date: date = None,
        **kwargs,
    ) -> Dict:
        """Create task via available provider."""
        svc = self.tasks
        if not svc:
            raise RuntimeError("No task service connected")
        return await svc.create_task(title=title, due_date=due_date, **kwargs)


# Singleton instance
_unified_services: Optional[UnifiedServices] = None


def get_unified_services() -> UnifiedServices:
    """Get or create the unified services singleton."""
    global _unified_services
    if _unified_services is None:
        _unified_services = UnifiedServices()
    return _unified_services
