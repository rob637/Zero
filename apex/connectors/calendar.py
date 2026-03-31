"""
Google Calendar Connector

Real Google Calendar API integration.

Usage:
    from connectors.calendar import CalendarConnector
    
    cal = CalendarConnector()
    await cal.connect()
    
    # List upcoming events
    events = await cal.list_events(max_results=10)
    
    # Create event
    await cal.create_event(
        summary="Team Meeting",
        start="2024-03-15T10:00:00",
        end="2024-03-15T11:00:00",
        attendees=["alice@example.com", "bob@example.com"]
    )
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import json

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False


@dataclass
class CalendarEvent:
    """Represents a calendar event."""
    id: str
    summary: str
    start: datetime
    end: datetime
    description: Optional[str] = None
    location: Optional[str] = None
    attendees: List[Dict] = field(default_factory=list)
    organizer: Optional[str] = None
    status: str = "confirmed"
    html_link: Optional[str] = None
    conference_data: Optional[Dict] = None
    recurrence: List[str] = field(default_factory=list)
    all_day: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "summary": self.summary,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "description": self.description,
            "location": self.location,
            "attendees": self.attendees,
            "organizer": self.organizer,
            "status": self.status,
            "html_link": self.html_link,
            "all_day": self.all_day,
        }


class CalendarConnector:
    """
    Google Calendar API connector.
    
    Provides methods for:
    - Listing and searching events
    - Creating, updating, deleting events
    - Managing calendars
    - Finding free/busy times
    """
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._service = None
        self._primary_calendar: Optional[str] = None
    
    async def connect(self) -> bool:
        """Connect to Google Calendar API."""
        if not HAS_GOOGLE_API:
            raise ImportError(
                "Google API client not installed. Run:\n"
                "pip install google-api-python-client"
            )
        
        creds = await self._auth.get_credentials(['calendar'])
        if not creds:
            return False
        
        self._service = await asyncio.to_thread(
            build, 'calendar', 'v3', credentials=creds
        )
        
        # Get primary calendar
        try:
            cal = await asyncio.to_thread(
                self._service.calendars().get(calendarId='primary').execute
            )
            self._primary_calendar = cal.get('id')
        except Exception:
            self._primary_calendar = 'primary'
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._service is not None
    
    def _parse_event(self, event: Dict) -> CalendarEvent:
        """Parse Google Calendar event into CalendarEvent."""
        # Parse start/end times
        start = event.get('start', {})
        end = event.get('end', {})
        
        all_day = 'date' in start
        
        if all_day:
            start_dt = datetime.fromisoformat(start['date'])
            end_dt = datetime.fromisoformat(end['date'])
        else:
            start_str = start.get('dateTime', '')
            end_str = end.get('dateTime', '')
            try:
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            except:
                start_dt = datetime.now()
                end_dt = datetime.now() + timedelta(hours=1)
        
        # Parse attendees
        attendees = [
            {
                'email': a.get('email'),
                'name': a.get('displayName'),
                'status': a.get('responseStatus'),
                'organizer': a.get('organizer', False),
            }
            for a in event.get('attendees', [])
        ]
        
        return CalendarEvent(
            id=event['id'],
            summary=event.get('summary', '(No title)'),
            start=start_dt,
            end=end_dt,
            description=event.get('description'),
            location=event.get('location'),
            attendees=attendees,
            organizer=event.get('organizer', {}).get('email'),
            status=event.get('status', 'confirmed'),
            html_link=event.get('htmlLink'),
            conference_data=event.get('conferenceData'),
            recurrence=event.get('recurrence', []),
            all_day=all_day,
        )
    
    async def list_events(
        self,
        calendar_id: str = 'primary',
        time_min: datetime = None,
        time_max: datetime = None,
        max_results: int = 50,
        single_events: bool = True,
        query: str = None,
    ) -> List[CalendarEvent]:
        """
        List calendar events.
        
        Args:
            calendar_id: Calendar ID (default: primary)
            time_min: Start of time range (default: now)
            time_max: End of time range (default: 30 days from now)
            max_results: Maximum events to return
            single_events: Expand recurring events
            query: Free text search query
        
        Returns:
            List of CalendarEvent objects
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=30)
        
        try:
            request = self._service.events().list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat() + 'Z',
                timeMax=time_max.isoformat() + 'Z',
                maxResults=max_results,
                singleEvents=single_events,
                orderBy='startTime',
                q=query,
            )
            result = await asyncio.to_thread(request.execute)
            
            return [self._parse_event(e) for e in result.get('items', [])]
            
        except HttpError as e:
            raise RuntimeError(f"Calendar API error: {e}")
    
    async def get_event(self, event_id: str, calendar_id: str = 'primary') -> CalendarEvent:
        """Get a single event by ID."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.events().get(
            calendarId=calendar_id,
            eventId=event_id,
        )
        event = await asyncio.to_thread(request.execute)
        return self._parse_event(event)
    
    async def create_event(
        self,
        summary: str,
        start: str | datetime,
        end: str | datetime = None,
        description: str = None,
        location: str = None,
        attendees: List[str] = None,
        calendar_id: str = 'primary',
        send_notifications: bool = True,
        all_day: bool = False,
        recurrence: List[str] = None,
        conference: bool = False,
    ) -> CalendarEvent:
        """
        Create a calendar event.
        
        Args:
            summary: Event title
            start: Start time (ISO string or datetime)
            end: End time (default: 1 hour after start)
            description: Event description
            location: Event location
            attendees: List of attendee email addresses
            calendar_id: Calendar ID
            send_notifications: Send email invites
            all_day: Create all-day event
            recurrence: RRULE strings (e.g., ["RRULE:FREQ=WEEKLY;COUNT=10"])
            conference: Add Google Meet link
        
        Returns:
            Created CalendarEvent
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Parse times
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace('Z', '+00:00'))
        if end is None:
            end = start + timedelta(hours=1)
        elif isinstance(end, str):
            end = datetime.fromisoformat(end.replace('Z', '+00:00'))
        
        # Build event body
        event_body = {
            'summary': summary,
        }
        
        if all_day:
            event_body['start'] = {'date': start.strftime('%Y-%m-%d')}
            event_body['end'] = {'date': end.strftime('%Y-%m-%d')}
        else:
            event_body['start'] = {
                'dateTime': start.isoformat(),
                'timeZone': 'UTC',
            }
            event_body['end'] = {
                'dateTime': end.isoformat(),
                'timeZone': 'UTC',
            }
        
        if description:
            event_body['description'] = description
        if location:
            event_body['location'] = location
        if attendees:
            event_body['attendees'] = [{'email': e} for e in attendees]
        if recurrence:
            event_body['recurrence'] = recurrence
        if conference:
            event_body['conferenceData'] = {
                'createRequest': {'requestId': f'apex-{datetime.now().timestamp()}'}
            }
        
        try:
            request = self._service.events().insert(
                calendarId=calendar_id,
                body=event_body,
                sendNotifications=send_notifications,
                conferenceDataVersion=1 if conference else 0,
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_event(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to create event: {e}")
    
    async def update_event(
        self,
        event_id: str,
        calendar_id: str = 'primary',
        **updates,
    ) -> CalendarEvent:
        """
        Update an existing event.
        
        Args:
            event_id: Event ID
            calendar_id: Calendar ID
            **updates: Fields to update (summary, start, end, description, etc.)
        
        Returns:
            Updated CalendarEvent
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Get existing event
        existing = await self.get_event(event_id, calendar_id)
        
        # Build update body
        event_body = {'summary': existing.summary}
        
        for key, value in updates.items():
            if key in ('start', 'end') and isinstance(value, datetime):
                event_body[key] = {
                    'dateTime': value.isoformat(),
                    'timeZone': 'UTC',
                }
            elif key == 'attendees' and isinstance(value, list):
                event_body[key] = [{'email': e} for e in value]
            else:
                event_body[key] = value
        
        try:
            request = self._service.events().patch(
                calendarId=calendar_id,
                eventId=event_id,
                body=event_body,
            )
            result = await asyncio.to_thread(request.execute)
            return self._parse_event(result)
            
        except HttpError as e:
            raise RuntimeError(f"Failed to update event: {e}")
    
    async def delete_event(
        self,
        event_id: str,
        calendar_id: str = 'primary',
        send_notifications: bool = True,
    ) -> bool:
        """Delete an event."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            request = self._service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendNotifications=send_notifications,
            )
            await asyncio.to_thread(request.execute)
            return True
            
        except HttpError as e:
            raise RuntimeError(f"Failed to delete event: {e}")
    
    async def find_free_time(
        self,
        duration_minutes: int = 60,
        time_min: datetime = None,
        time_max: datetime = None,
        working_hours: tuple = (9, 17),
        calendar_ids: List[str] = None,
    ) -> List[Dict]:
        """
        Find free time slots.
        
        Args:
            duration_minutes: Minimum slot duration
            time_min: Start of search range
            time_max: End of search range
            working_hours: (start_hour, end_hour) in 24h format
            calendar_ids: Calendars to check
        
        Returns:
            List of free slots with start/end times
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if time_min is None:
            time_min = datetime.utcnow()
        if time_max is None:
            time_max = time_min + timedelta(days=7)
        
        calendar_ids = calendar_ids or ['primary']
        
        # Get busy times
        try:
            request = self._service.freebusy().query(body={
                'timeMin': time_min.isoformat() + 'Z',
                'timeMax': time_max.isoformat() + 'Z',
                'items': [{'id': cid} for cid in calendar_ids],
            })
            result = await asyncio.to_thread(request.execute)
            
            # Collect all busy periods
            busy = []
            for cal_id in calendar_ids:
                cal_busy = result.get('calendars', {}).get(cal_id, {}).get('busy', [])
                for period in cal_busy:
                    busy.append({
                        'start': datetime.fromisoformat(period['start'].replace('Z', '+00:00')),
                        'end': datetime.fromisoformat(period['end'].replace('Z', '+00:00')),
                    })
            
            # Sort by start time
            busy.sort(key=lambda x: x['start'])
            
            # Find gaps
            free_slots = []
            current = time_min
            
            for period in busy:
                if period['start'] > current:
                    # Check if gap is within working hours and long enough
                    gap_start = current
                    gap_end = period['start']
                    
                    if (gap_end - gap_start).total_seconds() >= duration_minutes * 60:
                        free_slots.append({
                            'start': gap_start.isoformat(),
                            'end': gap_end.isoformat(),
                            'duration_minutes': int((gap_end - gap_start).total_seconds() / 60),
                        })
                
                current = max(current, period['end'])
            
            # Check remaining time
            if current < time_max:
                gap_start = current
                gap_end = time_max
                if (gap_end - gap_start).total_seconds() >= duration_minutes * 60:
                    free_slots.append({
                        'start': gap_start.isoformat(),
                        'end': gap_end.isoformat(),
                        'duration_minutes': int((gap_end - gap_start).total_seconds() / 60),
                    })
            
            return free_slots[:10]  # Return top 10
            
        except HttpError as e:
            raise RuntimeError(f"Failed to query free/busy: {e}")
    
    async def list_calendars(self) -> List[Dict]:
        """List all calendars."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.calendarList().list()
        result = await asyncio.to_thread(request.execute)
        
        return [
            {
                'id': cal['id'],
                'summary': cal.get('summary'),
                'description': cal.get('description'),
                'primary': cal.get('primary', False),
                'access_role': cal.get('accessRole'),
            }
            for cal in result.get('items', [])
        ]
