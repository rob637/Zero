"""
Google Service Connectors for Apex Integration Platform

Real, working integrations with Google services:
- Gmail: Read, send, label, archive
- Calendar: Create, update, delete events
- Drive: Create, read, update files

All operations go through the credential manager for secure OAuth.
"""

import asyncio
import base64
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import httpx

from ..integrations.credential_manager import get_credential_manager, OAuth2Credentials
from ..integrations.event_bus import get_event_bus, Event, GmailEvents, CalendarEvents, DriveEvents
from ..integrations.context_engine import get_context_engine

logger = logging.getLogger(__name__)


class GoogleConnectorBase:
    """Base class for Google service connectors."""
    
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.cred_manager = get_credential_manager()
        self.event_bus = get_event_bus()
        self.context = get_context_engine()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def get_client(self) -> httpx.AsyncClient:
        """Get authenticated HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers."""
        token = await self.cred_manager.get_valid_token(self.service_name)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    
    async def _request(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """Make authenticated request to Google API."""
        client = await self.get_client()
        headers = await self._get_headers()
        
        response = await client.request(
            method,
            url,
            headers=headers,
            **kwargs,
        )
        
        if response.status_code == 401:
            # Token expired, refresh and retry
            await self.cred_manager.refresh_oauth2(self.service_name)
            headers = await self._get_headers()
            response = await client.request(
                method,
                url,
                headers=headers,
                **kwargs,
            )
        
        response.raise_for_status()
        return response.json() if response.content else {}
    
    def is_connected(self) -> bool:
        """Check if service is authenticated."""
        return self.cred_manager.has_credentials(self.service_name)
    
    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


@dataclass
class Email:
    """Email data structure."""
    id: str
    thread_id: str
    subject: str
    sender: str
    to: List[str]
    cc: List[str] = field(default_factory=list)
    date: Optional[datetime] = None
    snippet: str = ""
    body: str = ""
    labels: List[str] = field(default_factory=list)
    is_unread: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "sender": self.sender,
            "to": self.to,
            "cc": self.cc,
            "date": self.date.isoformat() if self.date else None,
            "snippet": self.snippet,
            "body": self.body,
            "labels": self.labels,
            "is_unread": self.is_unread,
            "attachments": self.attachments,
        }


class GmailConnector(GoogleConnectorBase):
    """
    Gmail integration - full email access.
    
    Capabilities:
    - List/search emails
    - Read email content
    - Send emails
    - Apply/remove labels
    - Archive/delete
    """
    
    BASE_URL = "https://gmail.googleapis.com/gmail/v1"
    
    def __init__(self):
        super().__init__("gmail")
    
    async def list_messages(
        self,
        query: str = "",
        label_ids: Optional[List[str]] = None,
        max_results: int = 20,
        include_body: bool = False,
    ) -> List[Email]:
        """
        List emails matching criteria.
        
        Args:
            query: Gmail search query (e.g., "from:john@example.com is:unread")
            label_ids: Filter by label IDs
            max_results: Maximum emails to return
            include_body: Whether to fetch full body (slower)
        
        Returns:
            List of Email objects
        """
        params = {"maxResults": max_results}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = ",".join(label_ids)
        
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/users/me/messages",
            params=params,
        )
        
        messages = response.get("messages", [])
        emails = []
        
        for msg_summary in messages:
            email = await self.get_message(msg_summary["id"], include_body=include_body)
            if email:
                emails.append(email)
        
        return emails
    
    async def get_message(self, message_id: str, include_body: bool = True) -> Optional[Email]:
        """Get full email by ID."""
        try:
            format_type = "full" if include_body else "metadata"
            response = await self._request(
                "GET",
                f"{self.BASE_URL}/users/me/messages/{message_id}",
                params={"format": format_type},
            )
            
            return self._parse_message(response)
        except Exception as e:
            logger.error(f"Failed to get message {message_id}: {e}")
            return None
    
    def _parse_message(self, data: Dict[str, Any]) -> Email:
        """Parse Gmail API message into Email object."""
        headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        
        # Parse date
        date = None
        if internalDate := data.get("internalDate"):
            date = datetime.fromtimestamp(int(internalDate) / 1000)
        
        # Parse body
        body = ""
        payload = data.get("payload", {})
        if "body" in payload and payload["body"].get("data"):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
        elif "parts" in payload:
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
                    break
        
        # Parse attachments
        attachments = []
        if "parts" in payload:
            for part in payload["parts"]:
                if part.get("filename"):
                    attachments.append({
                        "id": part.get("body", {}).get("attachmentId"),
                        "filename": part["filename"],
                        "mimeType": part.get("mimeType"),
                        "size": part.get("body", {}).get("size"),
                    })
        
        # Parse recipients
        to = [x.strip() for x in headers.get("to", "").split(",")] if headers.get("to") else []
        cc = [x.strip() for x in headers.get("cc", "").split(",")] if headers.get("cc") else []
        
        return Email(
            id=data["id"],
            thread_id=data["threadId"],
            subject=headers.get("subject", "(no subject)"),
            sender=headers.get("from", ""),
            to=to,
            cc=cc,
            date=date,
            snippet=data.get("snippet", ""),
            body=body,
            labels=data.get("labelIds", []),
            is_unread="UNREAD" in data.get("labelIds", []),
            attachments=attachments,
        )
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send an email.
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body (plain text)
            cc: Optional CC recipients
            reply_to: Message ID to reply to
            thread_id: Thread ID for threading
        
        Returns:
            Sent message info
        """
        message = MIMEMultipart()
        message["to"] = ", ".join(to)
        message["subject"] = subject
        if cc:
            message["cc"] = ", ".join(cc)
        
        message.attach(MIMEText(body, "plain"))
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        
        body_data = {"raw": raw}
        if thread_id:
            body_data["threadId"] = thread_id
        
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/users/me/messages/send",
            json=body_data,
        )
        
        # Emit event
        await self.event_bus.emit(Event(
            service="gmail",
            event_type=GmailEvents.EMAIL_SENT,
            data={
                "to": to,
                "subject": subject,
                "thread_id": thread_id,
            },
        ))
        
        logger.info(f"Email sent to {to}")
        return response
    
    async def add_labels(self, message_id: str, label_ids: List[str]) -> Dict[str, Any]:
        """Add labels to a message."""
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/users/me/messages/{message_id}/modify",
            json={"addLabelIds": label_ids},
        )
        
        await self.event_bus.emit(Event(
            service="gmail",
            event_type=GmailEvents.LABEL_ADDED,
            data={"message_id": message_id, "labels": label_ids},
        ))
        
        return response
    
    async def remove_labels(self, message_id: str, label_ids: List[str]) -> Dict[str, Any]:
        """Remove labels from a message."""
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/users/me/messages/{message_id}/modify",
            json={"removeLabelIds": label_ids},
        )
        
        await self.event_bus.emit(Event(
            service="gmail",
            event_type=GmailEvents.LABEL_REMOVED,
            data={"message_id": message_id, "labels": label_ids},
        ))
        
        return response
    
    async def archive(self, message_id: str) -> Dict[str, Any]:
        """Archive a message (remove INBOX label)."""
        return await self.remove_labels(message_id, ["INBOX"])
    
    async def mark_read(self, message_id: str) -> Dict[str, Any]:
        """Mark message as read."""
        return await self.remove_labels(message_id, ["UNREAD"])
    
    async def mark_unread(self, message_id: str) -> Dict[str, Any]:
        """Mark message as unread."""
        return await self.add_labels(message_id, ["UNREAD"])
    
    async def trash(self, message_id: str) -> Dict[str, Any]:
        """Move message to trash."""
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/users/me/messages/{message_id}/trash",
        )
        
        await self.event_bus.emit(Event(
            service="gmail",
            event_type=GmailEvents.EMAIL_DELETED,
            data={"message_id": message_id},
        ))
        
        return response
    
    async def list_labels(self) -> List[Dict[str, str]]:
        """List all Gmail labels."""
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/users/me/labels",
        )
        return response.get("labels", [])
    
    async def create_label(self, name: str) -> Dict[str, Any]:
        """Create a new label."""
        return await self._request(
            "POST",
            f"{self.BASE_URL}/users/me/labels",
            json={"name": name},
        )
    
    async def get_unread_count(self) -> int:
        """Get count of unread emails."""
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/users/me/labels/UNREAD",
        )
        return response.get("messagesUnread", 0)


@dataclass
class CalendarEvent:
    """Calendar event data structure."""
    id: str
    summary: str
    description: str = ""
    location: str = ""
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    all_day: bool = False
    attendees: List[Dict[str, str]] = field(default_factory=list)
    organizer: Optional[Dict[str, str]] = None
    calendar_id: str = "primary"
    html_link: str = ""
    recurrence: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "description": self.description,
            "location": self.location,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "all_day": self.all_day,
            "attendees": self.attendees,
            "organizer": self.organizer,
            "calendar_id": self.calendar_id,
            "html_link": self.html_link,
            "recurrence": self.recurrence,
        }


class GoogleCalendarConnector(GoogleConnectorBase):
    """
    Google Calendar integration.
    
    Capabilities:
    - List calendars
    - List/search events
    - Create/update/delete events
    - Accept/decline invites
    """
    
    BASE_URL = "https://www.googleapis.com/calendar/v3"
    
    def __init__(self):
        super().__init__("calendar")
    
    async def list_calendars(self) -> List[Dict[str, Any]]:
        """List all calendars."""
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/users/me/calendarList",
        )
        return response.get("items", [])
    
    async def list_events(
        self,
        calendar_id: str = "primary",
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 50,
        query: Optional[str] = None,
    ) -> List[CalendarEvent]:
        """
        List calendar events.
        
        Args:
            calendar_id: Calendar ID (default: primary)
            time_min: Start of time range
            time_max: End of time range
            max_results: Maximum events to return
            query: Search query
        
        Returns:
            List of CalendarEvent objects
        """
        params = {
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        
        if time_min:
            params["timeMin"] = time_min.isoformat() + "Z"
        else:
            params["timeMin"] = datetime.utcnow().isoformat() + "Z"
        
        if time_max:
            params["timeMax"] = time_max.isoformat() + "Z"
        
        if query:
            params["q"] = query
        
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/calendars/{calendar_id}/events",
            params=params,
        )
        
        events = []
        for item in response.get("items", []):
            events.append(self._parse_event(item, calendar_id))
        
        return events
    
    def _parse_event(self, data: Dict[str, Any], calendar_id: str) -> CalendarEvent:
        """Parse Google Calendar event."""
        start_data = data.get("start", {})
        end_data = data.get("end", {})
        
        all_day = "date" in start_data
        
        if all_day:
            start = datetime.fromisoformat(start_data["date"])
            end = datetime.fromisoformat(end_data["date"])
        else:
            start_str = start_data.get("dateTime", "")
            end_str = end_data.get("dateTime", "")
            start = datetime.fromisoformat(start_str.replace("Z", "+00:00")) if start_str else None
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00")) if end_str else None
        
        return CalendarEvent(
            id=data["id"],
            summary=data.get("summary", "(no title)"),
            description=data.get("description", ""),
            location=data.get("location", ""),
            start=start,
            end=end,
            all_day=all_day,
            attendees=data.get("attendees", []),
            organizer=data.get("organizer"),
            calendar_id=calendar_id,
            html_link=data.get("htmlLink", ""),
            recurrence=data.get("recurrence", []),
        )
    
    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        calendar_id: str = "primary",
        all_day: bool = False,
    ) -> CalendarEvent:
        """
        Create a calendar event.
        
        Args:
            summary: Event title
            start: Start time
            end: End time
            description: Event description
            location: Event location
            attendees: List of email addresses
            calendar_id: Target calendar
            all_day: Whether this is an all-day event
        
        Returns:
            Created CalendarEvent
        """
        event_data = {
            "summary": summary,
            "description": description,
            "location": location,
        }
        
        if all_day:
            event_data["start"] = {"date": start.strftime("%Y-%m-%d")}
            event_data["end"] = {"date": end.strftime("%Y-%m-%d")}
        else:
            event_data["start"] = {"dateTime": start.isoformat(), "timeZone": "UTC"}
            event_data["end"] = {"dateTime": end.isoformat(), "timeZone": "UTC"}
        
        if attendees:
            event_data["attendees"] = [{"email": email} for email in attendees]
        
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/calendars/{calendar_id}/events",
            json=event_data,
        )
        
        # Emit event
        await self.event_bus.emit(Event(
            service="calendar",
            event_type=CalendarEvents.EVENT_CREATED,
            data={
                "summary": summary,
                "start": start.isoformat(),
                "attendees": attendees or [],
            },
        ))
        
        logger.info(f"Calendar event created: {summary}")
        return self._parse_event(response, calendar_id)
    
    async def update_event(
        self,
        event_id: str,
        calendar_id: str = "primary",
        **updates,
    ) -> CalendarEvent:
        """Update an existing event."""
        response = await self._request(
            "PATCH",
            f"{self.BASE_URL}/calendars/{calendar_id}/events/{event_id}",
            json=updates,
        )
        
        await self.event_bus.emit(Event(
            service="calendar",
            event_type=CalendarEvents.EVENT_UPDATED,
            data={"event_id": event_id, "updates": updates},
        ))
        
        return self._parse_event(response, calendar_id)
    
    async def delete_event(self, event_id: str, calendar_id: str = "primary") -> bool:
        """Delete a calendar event."""
        try:
            await self._request(
                "DELETE",
                f"{self.BASE_URL}/calendars/{calendar_id}/events/{event_id}",
            )
            
            await self.event_bus.emit(Event(
                service="calendar",
                event_type=CalendarEvents.EVENT_DELETED,
                data={"event_id": event_id},
            ))
            
            logger.info(f"Calendar event deleted: {event_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete event: {e}")
            return False
    
    async def get_next_event(self, calendar_id: str = "primary") -> Optional[CalendarEvent]:
        """Get the next upcoming event."""
        events = await self.list_events(
            calendar_id=calendar_id,
            time_min=datetime.utcnow(),
            max_results=1,
        )
        return events[0] if events else None
    
    async def get_today_events(self, calendar_id: str = "primary") -> List[CalendarEvent]:
        """Get all events for today."""
        now = datetime.utcnow()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        return await self.list_events(
            calendar_id=calendar_id,
            time_min=start_of_day,
            time_max=end_of_day,
        )


@dataclass
class DriveFile:
    """Google Drive file data structure."""
    id: str
    name: str
    mime_type: str
    size: int = 0
    created_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    parents: List[str] = field(default_factory=list)
    web_view_link: str = ""
    owners: List[Dict[str, str]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "size": self.size,
            "created_time": self.created_time.isoformat() if self.created_time else None,
            "modified_time": self.modified_time.isoformat() if self.modified_time else None,
            "parents": self.parents,
            "web_view_link": self.web_view_link,
            "owners": self.owners,
        }


class GoogleDriveConnector(GoogleConnectorBase):
    """
    Google Drive integration.
    
    Capabilities:
    - List/search files
    - Create/upload files
    - Update files
    - Share files
    - Create folders
    """
    
    BASE_URL = "https://www.googleapis.com/drive/v3"
    UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
    
    def __init__(self):
        super().__init__("drive")
    
    async def list_files(
        self,
        query: Optional[str] = None,
        folder_id: Optional[str] = None,
        mime_type: Optional[str] = None,
        max_results: int = 50,
    ) -> List[DriveFile]:
        """
        List files in Drive.
        
        Args:
            query: Drive search query
            folder_id: List files in specific folder
            mime_type: Filter by MIME type
            max_results: Maximum files to return
        
        Returns:
            List of DriveFile objects
        """
        q_parts = []
        
        if query:
            q_parts.append(f"fullText contains '{query}'")
        
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        
        if mime_type:
            q_parts.append(f"mimeType = '{mime_type}'")
        
        # Exclude trashed files
        q_parts.append("trashed = false")
        
        params = {
            "pageSize": max_results,
            "fields": "files(id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink,owners)",
        }
        
        if q_parts:
            params["q"] = " and ".join(q_parts)
        
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/files",
            params=params,
        )
        
        files = []
        for item in response.get("files", []):
            files.append(self._parse_file(item))
        
        return files
    
    def _parse_file(self, data: Dict[str, Any]) -> DriveFile:
        """Parse Drive file response."""
        created = None
        modified = None
        
        if data.get("createdTime"):
            created = datetime.fromisoformat(data["createdTime"].replace("Z", "+00:00"))
        if data.get("modifiedTime"):
            modified = datetime.fromisoformat(data["modifiedTime"].replace("Z", "+00:00"))
        
        return DriveFile(
            id=data["id"],
            name=data["name"],
            mime_type=data.get("mimeType", ""),
            size=int(data.get("size", 0)),
            created_time=created,
            modified_time=modified,
            parents=data.get("parents", []),
            web_view_link=data.get("webViewLink", ""),
            owners=data.get("owners", []),
        )
    
    async def get_file(self, file_id: str) -> DriveFile:
        """Get file metadata by ID."""
        response = await self._request(
            "GET",
            f"{self.BASE_URL}/files/{file_id}",
            params={"fields": "id,name,mimeType,size,createdTime,modifiedTime,parents,webViewLink,owners"},
        )
        return self._parse_file(response)
    
    async def create_file(
        self,
        name: str,
        content: str,
        mime_type: str = "text/plain",
        folder_id: Optional[str] = None,
    ) -> DriveFile:
        """
        Create a new file with content.
        
        Args:
            name: File name
            content: File content
            mime_type: MIME type of content
            folder_id: Parent folder ID
        
        Returns:
            Created DriveFile
        """
        metadata = {"name": name}
        if folder_id:
            metadata["parents"] = [folder_id]
        
        # Multipart upload
        client = await self.get_client()
        headers = await self._get_headers()
        
        # Use resumable upload for simplicity
        headers["Content-Type"] = "application/json"
        
        # Create file metadata
        init_response = await client.post(
            f"{self.UPLOAD_URL}/files",
            headers=headers,
            params={"uploadType": "multipart"},
            json=metadata,
        )
        
        # Actually upload with content
        # For small files, use simple upload
        boundary = "apex_boundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Type: application/json\r\n\r\n'
            f'{{"name": "{name}"'
        )
        if folder_id:
            body += f', "parents": ["{folder_id}"]'
        body += (
            f'}}\r\n'
            f'--{boundary}\r\n'
            f'Content-Type: {mime_type}\r\n\r\n'
            f'{content}\r\n'
            f'--{boundary}--'
        )
        
        headers["Content-Type"] = f"multipart/related; boundary={boundary}"
        
        response = await client.post(
            f"{self.UPLOAD_URL}/files",
            params={"uploadType": "multipart", "fields": "id,name,mimeType,webViewLink"},
            headers=headers,
            content=body.encode(),
        )
        
        response.raise_for_status()
        data = response.json()
        
        # Emit event
        await self.event_bus.emit(Event(
            service="drive",
            event_type=DriveEvents.FILE_CREATED,
            data={"name": name, "id": data["id"]},
        ))
        
        logger.info(f"Drive file created: {name}")
        return self._parse_file(data)
    
    async def create_folder(self, name: str, parent_id: Optional[str] = None) -> DriveFile:
        """Create a new folder."""
        metadata = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]
        
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/files",
            json=metadata,
        )
        
        await self.event_bus.emit(Event(
            service="drive",
            event_type=DriveEvents.FOLDER_CREATED,
            data={"name": name, "id": response["id"]},
        ))
        
        return self._parse_file(response)
    
    async def update_file(
        self,
        file_id: str,
        content: Optional[str] = None,
        name: Optional[str] = None,
    ) -> DriveFile:
        """Update file content or metadata."""
        updates = {}
        if name:
            updates["name"] = name
        
        if content:
            # Upload new content
            client = await self.get_client()
            headers = await self._get_headers()
            headers["Content-Type"] = "text/plain"
            
            response = await client.patch(
                f"{self.UPLOAD_URL}/files/{file_id}",
                params={"uploadType": "media", "fields": "id,name,mimeType,webViewLink"},
                headers=headers,
                content=content.encode(),
            )
            response.raise_for_status()
            data = response.json()
        elif updates:
            data = await self._request(
                "PATCH",
                f"{self.BASE_URL}/files/{file_id}",
                json=updates,
            )
        else:
            return await self.get_file(file_id)
        
        await self.event_bus.emit(Event(
            service="drive",
            event_type=DriveEvents.FILE_MODIFIED,
            data={"file_id": file_id},
        ))
        
        return self._parse_file(data)
    
    async def delete_file(self, file_id: str) -> bool:
        """Delete a file (move to trash)."""
        try:
            await self._request(
                "DELETE",
                f"{self.BASE_URL}/files/{file_id}",
            )
            
            await self.event_bus.emit(Event(
                service="drive",
                event_type=DriveEvents.FILE_DELETED,
                data={"file_id": file_id},
            ))
            
            return True
        except Exception as e:
            logger.error(f"Failed to delete file: {e}")
            return False
    
    async def share_file(
        self,
        file_id: str,
        email: str,
        role: str = "reader",
    ) -> Dict[str, Any]:
        """
        Share a file with someone.
        
        Args:
            file_id: File to share
            email: Email address to share with
            role: Permission role (reader, writer, commenter)
        
        Returns:
            Permission info
        """
        permission = {
            "type": "user",
            "role": role,
            "emailAddress": email,
        }
        
        response = await self._request(
            "POST",
            f"{self.BASE_URL}/files/{file_id}/permissions",
            json=permission,
        )
        
        await self.event_bus.emit(Event(
            service="drive",
            event_type=DriveEvents.FILE_SHARED,
            data={"file_id": file_id, "email": email, "role": role},
        ))
        
        return response
    
    async def download_file(self, file_id: str) -> bytes:
        """Download file content."""
        client = await self.get_client()
        headers = await self._get_headers()
        
        response = await client.get(
            f"{self.BASE_URL}/files/{file_id}",
            params={"alt": "media"},
            headers=headers,
        )
        
        response.raise_for_status()
        return response.content
    
    async def search(self, query: str, max_results: int = 20) -> List[DriveFile]:
        """Search for files by name or content."""
        return await self.list_files(query=query, max_results=max_results)


# Factory function to get connectors
def get_gmail_connector() -> GmailConnector:
    """Get Gmail connector instance."""
    return GmailConnector()


def get_calendar_connector() -> GoogleCalendarConnector:
    """Get Google Calendar connector instance."""
    return GoogleCalendarConnector()


def get_drive_connector() -> GoogleDriveConnector:
    """Get Google Drive connector instance."""
    return GoogleDriveConnector()
