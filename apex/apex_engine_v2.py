"""
Telic Engine v2 - With Real Google Integration

This version includes real Google API connectors for Gmail, Calendar, Drive, and Contacts.

Usage:
    from apex_engine_v2 import Apex
    
    engine = Apex(api_key="...")
    
    # Connect to Google services (first run opens browser for OAuth)
    await engine.connect_google()
    
    # Now requests can use real Gmail, Calendar, etc.
    result = await engine.do("Find my unread emails from this week")
    result = await engine.do("What meetings do I have tomorrow?")
    result = await engine.do("Find the budget spreadsheet in my Drive")
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

# Import base engine components
from apex.apex_engine import (
    Apex as BaseApex,
    Primitive,
    StepResult,
    PlanStep,
    ExecutionResult,
    FilePrimitive,
    DocumentPrimitive,
    ComputePrimitive,
    KnowledgePrimitive,
)

# Import connectors
try:
    from apex.connectors import (
        GoogleAuth, get_google_auth,
        GmailConnector, CalendarConnector, DriveConnector, ContactsConnector,
    )
    HAS_CONNECTORS = True
except ImportError:
    HAS_CONNECTORS = False

logger = logging.getLogger(__name__)


# ============================================================
#  GMAIL PRIMITIVE (Real API)
# ============================================================

class GmailPrimitive(Primitive):
    """Gmail operations using real Google API."""
    
    def __init__(self, connector: 'GmailConnector' = None):
        self._connector = connector
        self._mock_mode = connector is None
    
    @property
    def name(self) -> str:
        return "EMAIL"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "send": "Send an email",
            "draft": "Create a draft email",
            "search": "Search emails",
            "list": "List recent emails",
            "read": "Read a specific email",
            "mark_read": "Mark email as read",
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if self._mock_mode or not self._connector or not self._connector.connected:
            return StepResult(False, error="Gmail not connected. Call connect_google() first.")
        
        try:
            if operation == "send":
                result = await self._connector.send_email(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body"),
                    cc=params.get("cc"),
                    attachments=params.get("attachments"),
                )
                return StepResult(True, data=result)
            
            elif operation == "draft":
                result = await self._connector.create_draft(
                    to=params.get("to"),
                    subject=params.get("subject"),
                    body=params.get("body"),
                )
                return StepResult(True, data=result)
            
            elif operation == "search":
                emails = await self._connector.search(
                    query=params.get("query", ""),
                    max_results=params.get("max_results", 20),
                )
                return StepResult(True, data=[e.to_dict() for e in emails])
            
            elif operation == "list":
                emails = await self._connector.list_messages(
                    query=params.get("query", ""),
                    max_results=params.get("max_results", 20),
                    label_ids=params.get("labels"),
                    include_body=params.get("include_body", False),
                )
                return StepResult(True, data=[e.to_dict() for e in emails])
            
            elif operation == "read":
                email = await self._connector.get_message(params.get("message_id"))
                return StepResult(True, data=email.to_dict())
            
            elif operation == "mark_read":
                await self._connector.mark_read(params.get("message_id"))
                return StepResult(True, data={"marked_read": True})
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CALENDAR PRIMITIVE (Real API)
# ============================================================

class CalendarPrimitive(Primitive):
    """Calendar operations using real Google API."""
    
    def __init__(self, connector: 'CalendarConnector' = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "CALENDAR"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list": "List upcoming events",
            "search": "Search events",
            "create": "Create an event",
            "update": "Update an event",
            "delete": "Delete an event",
            "find_free_time": "Find available time slots",
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector or not self._connector.connected:
            return StepResult(False, error="Calendar not connected. Call connect_google() first.")
        
        try:
            if operation == "list":
                time_min = params.get("time_min")
                time_max = params.get("time_max")
                
                if isinstance(time_min, str):
                    time_min = datetime.fromisoformat(time_min.replace('Z', '+00:00'))
                if isinstance(time_max, str):
                    time_max = datetime.fromisoformat(time_max.replace('Z', '+00:00'))
                
                events = await self._connector.list_events(
                    time_min=time_min,
                    time_max=time_max,
                    max_results=params.get("max_results", 20),
                    query=params.get("query"),
                )
                return StepResult(True, data=[e.to_dict() for e in events])
            
            elif operation == "search":
                events = await self._connector.list_events(
                    query=params.get("query"),
                    max_results=params.get("max_results", 20),
                )
                return StepResult(True, data=[e.to_dict() for e in events])
            
            elif operation == "create":
                event = await self._connector.create_event(
                    summary=params.get("summary"),
                    start=params.get("start"),
                    end=params.get("end"),
                    description=params.get("description"),
                    location=params.get("location"),
                    attendees=params.get("attendees"),
                    conference=params.get("add_meet", False),
                )
                return StepResult(True, data=event.to_dict())
            
            elif operation == "update":
                event = await self._connector.update_event(
                    event_id=params.get("event_id"),
                    **{k: v for k, v in params.items() if k != "event_id"},
                )
                return StepResult(True, data=event.to_dict())
            
            elif operation == "delete":
                await self._connector.delete_event(params.get("event_id"))
                return StepResult(True, data={"deleted": True})
            
            elif operation == "find_free_time":
                slots = await self._connector.find_free_time(
                    duration_minutes=params.get("duration_minutes", 60),
                )
                return StepResult(True, data=slots)
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  DRIVE PRIMITIVE (Real API)
# ============================================================

class DrivePrimitive(Primitive):
    """Google Drive operations using real API."""
    
    def __init__(self, connector: 'DriveConnector' = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "DRIVE"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "list": "List files",
            "search": "Search files by name or content",
            "download": "Download a file",
            "upload": "Upload a file",
            "create_folder": "Create a folder",
            "info": "Get file info",
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector or not self._connector.connected:
            return StepResult(False, error="Drive not connected. Call connect_google() first.")
        
        try:
            if operation == "list":
                files = await self._connector.list_files(
                    folder_id=params.get("folder_id"),
                    mime_type=params.get("type"),
                    max_results=params.get("max_results", 50),
                )
                return StepResult(True, data=[f.to_dict() for f in files])
            
            elif operation == "search":
                files = await self._connector.search(
                    name_contains=params.get("name"),
                    full_text=params.get("content"),
                    mime_type=params.get("type"),
                    max_results=params.get("max_results", 20),
                )
                return StepResult(True, data=[f.to_dict() for f in files])
            
            elif operation == "download":
                local_path = params.get("local_path")
                if local_path:
                    path = await self._connector.download_to_file(
                        file_id=params.get("file_id"),
                        local_path=local_path,
                        export_format=params.get("format"),
                    )
                    return StepResult(True, data={"path": path})
                else:
                    content = await self._connector.download_file(
                        file_id=params.get("file_id"),
                        export_format=params.get("format"),
                    )
                    return StepResult(True, data={"content": content.decode('utf-8', errors='ignore')})
            
            elif operation == "upload":
                file = await self._connector.upload_file(
                    local_path=params.get("local_path"),
                    name=params.get("name"),
                    folder_id=params.get("folder_id"),
                )
                return StepResult(True, data=file.to_dict())
            
            elif operation == "create_folder":
                folder = await self._connector.create_folder(
                    name=params.get("name"),
                    parent_id=params.get("parent_id"),
                )
                return StepResult(True, data=folder.to_dict())
            
            elif operation == "info":
                file = await self._connector.get_file(params.get("file_id"))
                return StepResult(True, data=file.to_dict())
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  CONTACTS PRIMITIVE (Real API)
# ============================================================

class GoogleContactsPrimitive(Primitive):
    """Contacts operations using real Google API."""
    
    def __init__(self, connector: 'ContactsConnector' = None):
        self._connector = connector
    
    @property
    def name(self) -> str:
        return "CONTACTS"
    
    def get_operations(self) -> Dict[str, str]:
        return {
            "search": "Search contacts by name or email",
            "find": "Find a specific contact",
            "list": "List all contacts",
            "create": "Create a new contact",
            "update": "Update a contact",
        }
    
    async def execute(self, operation: str, params: Dict[str, Any]) -> StepResult:
        if not self._connector or not self._connector.connected:
            return StepResult(False, error="Contacts not connected. Call connect_google() first.")
        
        try:
            if operation == "search":
                contacts = await self._connector.search(
                    query=params.get("query", ""),
                    max_results=params.get("max_results", 20),
                )
                return StepResult(True, data=[c.to_dict() for c in contacts])
            
            elif operation == "find":
                query = params.get("query") or params.get("name") or params.get("email", "")
                
                # Try by name first
                contact = await self._connector.find_by_name(query)
                if not contact and "@" in query:
                    contact = await self._connector.find_by_email(query)
                
                if contact:
                    return StepResult(True, data=contact.to_dict())
                return StepResult(True, data=None)
            
            elif operation == "list":
                contacts = await self._connector.list_contacts(
                    max_results=params.get("max_results", 100),
                )
                return StepResult(True, data=[c.to_dict() for c in contacts])
            
            elif operation == "create":
                contact = await self._connector.create_contact(
                    name=params.get("name"),
                    email=params.get("email"),
                    phone=params.get("phone"),
                    company=params.get("company"),
                    job_title=params.get("job_title"),
                )
                return StepResult(True, data=contact.to_dict())
            
            elif operation == "update":
                contact = await self._connector.update_contact(
                    resource_name=params.get("resource_name"),
                    **{k: v for k, v in params.items() if k != "resource_name"},
                )
                return StepResult(True, data=contact.to_dict())
            
            else:
                return StepResult(False, error=f"Unknown operation: {operation}")
                
        except Exception as e:
            return StepResult(False, error=str(e))


# ============================================================
#  TELIC ENGINE V2
# ============================================================

class Apex(BaseApex):
    """
    Enhanced Telic Engine with real Google integration.
    
    Usage:
        engine = Apex(api_key="...")
        await engine.connect_google()  # Authenticate with Google
        result = await engine.do("Find my unread emails")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        storage_path: Optional[str] = None,
    ):
        super().__init__(api_key=api_key, model=model, storage_path=storage_path)
        
        # Google connectors
        self._google_auth: Optional[GoogleAuth] = None
        self._gmail: Optional[GmailConnector] = None
        self._calendar: Optional[CalendarConnector] = None
        self._drive: Optional[DriveConnector] = None
        self._contacts: Optional[ContactsConnector] = None
        self._google_connected = False
    
    @property
    def google_connected(self) -> bool:
        return self._google_connected
    
    async def connect_google(self, scopes: List[str] = None) -> bool:
        """
        Connect to Google services.
        
        Opens browser for OAuth authentication on first use.
        Credentials are cached for future use.
        
        Args:
            scopes: List of services to connect ('gmail', 'calendar', 'drive', 'contacts')
                   Default: all services
        
        Returns:
            True if connected successfully
        """
        if not HAS_CONNECTORS:
            raise ImportError(
                "Google connectors not available. Install requirements:\n"
                "pip install google-auth google-auth-oauthlib google-api-python-client"
            )
        
        scopes = scopes or ['gmail', 'calendar', 'drive', 'contacts']
        
        # Initialize auth
        self._google_auth = get_google_auth(str(self._storage_path))
        
        if not self._google_auth.has_credentials_file():
            print(self._google_auth.get_setup_instructions())
            return False
        
        # Get credentials (will open browser if needed)
        print("Authenticating with Google...")
        creds = await self._google_auth.get_credentials(scopes)
        
        if not creds:
            return False
        
        # Connect services
        connected = []
        
        if 'gmail' in scopes:
            self._gmail = GmailConnector(self._google_auth)
            if await self._gmail.connect():
                self._primitives["EMAIL"] = GmailPrimitive(self._gmail)
                connected.append("Gmail")
        
        if 'calendar' in scopes:
            self._calendar = CalendarConnector(self._google_auth)
            if await self._calendar.connect():
                self._primitives["CALENDAR"] = CalendarPrimitive(self._calendar)
                connected.append("Calendar")
        
        if 'drive' in scopes:
            self._drive = DriveConnector(self._google_auth)
            if await self._drive.connect():
                self._primitives["DRIVE"] = DrivePrimitive(self._drive)
                connected.append("Drive")
        
        if 'contacts' in scopes:
            self._contacts = ContactsConnector(self._google_auth)
            if await self._contacts.connect():
                self._primitives["CONTACTS"] = GoogleContactsPrimitive(self._contacts)
                connected.append("Contacts")
        
        self._google_connected = len(connected) > 0
        
        if connected:
            print(f"✓ Connected to: {', '.join(connected)}")
        
        return self._google_connected
    
    def disconnect_google(self):
        """Disconnect from Google services."""
        if self._google_auth:
            self._google_auth.revoke()
        
        self._gmail = None
        self._calendar = None
        self._drive = None
        self._contacts = None
        self._google_connected = False
        
        # Restore basic primitives
        self._init_primitives()
    
    # === Convenience Methods ===
    
    async def get_unread_emails(self, max_results: int = 20) -> List[Dict]:
        """Get unread emails from inbox."""
        if not self._gmail:
            raise RuntimeError("Gmail not connected")
        
        emails = await self._gmail.list_messages(
            query="is:unread",
            max_results=max_results,
        )
        return [e.to_dict() for e in emails]
    
    async def send_email(self, to: str, subject: str, body: str) -> Dict:
        """Send an email."""
        if not self._gmail:
            raise RuntimeError("Gmail not connected")
        
        return await self._gmail.send_email(to=to, subject=subject, body=body)
    
    async def get_upcoming_events(self, days: int = 7) -> List[Dict]:
        """Get upcoming calendar events."""
        if not self._calendar:
            raise RuntimeError("Calendar not connected")
        
        events = await self._calendar.list_events(
            time_max=datetime.utcnow() + timedelta(days=days),
        )
        return [e.to_dict() for e in events]
    
    async def create_event(
        self,
        title: str,
        start: datetime,
        end: datetime = None,
        attendees: List[str] = None,
    ) -> Dict:
        """Create a calendar event."""
        if not self._calendar:
            raise RuntimeError("Calendar not connected")
        
        event = await self._calendar.create_event(
            summary=title,
            start=start,
            end=end,
            attendees=attendees,
        )
        return event.to_dict()
    
    async def search_drive(self, query: str) -> List[Dict]:
        """Search Google Drive."""
        if not self._drive:
            raise RuntimeError("Drive not connected")
        
        files = await self._drive.search(name_contains=query)
        return [f.to_dict() for f in files]
    
    async def find_contact(self, name: str) -> Optional[Dict]:
        """Find a contact by name."""
        if not self._contacts:
            raise RuntimeError("Contacts not connected")
        
        contact = await self._contacts.find_by_name(name)
        return contact.to_dict() if contact else None


# ============================================================
#  QUICK TEST
# ============================================================

async def test_google_integration():
    """Test Google integration (requires API credentials)."""
    apex = Apex()
    
    print("=" * 60)
    print(" TELIC v2 - Google Integration Test")
    print("=" * 60)
    
    # Check for credentials
    auth = get_google_auth()
    if not auth.has_credentials_file():
        print("\n⚠️  No Google credentials found.")
        print(auth.get_setup_instructions())
        return
    
    # Connect
    print("\nConnecting to Google services...")
    success = await apex.connect_google()
    
    if not success:
        print("❌ Failed to connect")
        return
    
    # Test Gmail
    print("\n📧 Testing Gmail...")
    try:
        result = await apex.get_primitive("EMAIL").execute("list", {
            "max_results": 5,
        })
        if result.success:
            print(f"   ✓ Found {len(result.data)} recent emails")
            for email in result.data[:3]:
                print(f"     - {email['subject'][:50]}... from {email['sender'][:30]}")
        else:
            print(f"   ✗ {result.error}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test Calendar
    print("\n📅 Testing Calendar...")
    try:
        result = await apex.get_primitive("CALENDAR").execute("list", {
            "max_results": 5,
        })
        if result.success:
            print(f"   ✓ Found {len(result.data)} upcoming events")
            for event in result.data[:3]:
                print(f"     - {event['summary']} at {event['start']}")
        else:
            print(f"   ✗ {result.error}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test Drive
    print("\n📁 Testing Drive...")
    try:
        result = await apex.get_primitive("DRIVE").execute("list", {
            "max_results": 5,
        })
        if result.success:
            print(f"   ✓ Found {len(result.data)} files")
            for f in result.data[:3]:
                print(f"     - {f['name']}")
        else:
            print(f"   ✗ {result.error}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    # Test Contacts
    print("\n👥 Testing Contacts...")
    try:
        result = await apex.get_primitive("CONTACTS").execute("list", {
            "max_results": 5,
        })
        if result.success:
            print(f"   ✓ Found {len(result.data)} contacts")
            for c in result.data[:3]:
                print(f"     - {c['name']} ({c.get('email', 'no email')})")
        else:
            print(f"   ✗ {result.error}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
    
    print("\n" + "=" * 60)
    print(" Capabilities with Google Connected")
    print("=" * 60)
    for name, ops in apex.list_capabilities().items():
        print(f"\n{name}:")
        for op, desc in ops.items():
            print(f"  • {op}: {desc}")


if __name__ == "__main__":
    asyncio.run(test_google_integration())
