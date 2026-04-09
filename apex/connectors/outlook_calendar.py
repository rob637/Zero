"""
Outlook Calendar Connector (Microsoft Graph API)

Full Microsoft Outlook Calendar integration:
- List and search events
- Create, update, delete events
- Recurring events support
- Find free/busy times
- Multiple calendar support
- Meeting invitations

Usage:
    from connectors.outlook_calendar import OutlookCalendarConnector
    
    calendar = OutlookCalendarConnector()
    await calendar.connect()
    
    # List events
    events = await calendar.list_events()
    
    # Create meeting
    event = await calendar.create_event(
        subject="Team Meeting",
        start="2024-01-15T10:00:00",
        end="2024-01-15T11:00:00",
        attendees=["bob@example.com"],
    )
    
    # Find free times
    free = await calendar.find_free_time(
        attendees=["bob@example.com", "alice@example.com"],
        duration_minutes=60,
    )
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

import logging
logger = logging.getLogger(__name__)


@dataclass
class CalendarEvent:
    """Represents an Outlook calendar event."""
    id: str
    subject: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    is_all_day: bool = False
    is_online: bool = False
    online_meeting_url: Optional[str] = None
    organizer: Optional[Dict] = None  # {name, email}
    attendees: List[Dict] = field(default_factory=list)  # [{name, email, status}, ...]
    is_cancelled: bool = False
    is_recurring: bool = False
    recurrence: Optional[Dict] = None
    reminder_minutes: int = 15
    show_as: str = "busy"  # free, tentative, busy, oof, workingElsewhere
    importance: str = "normal"
    sensitivity: str = "normal"  # normal, personal, private, confidential
    web_link: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "subject": self.subject,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "is_all_day": self.is_all_day,
        }
        if self.location:
            d["location"] = self.location
        if self.description:
            d["description"] = self.description[:200] + '...' if len(self.description) > 200 else self.description
        if self.is_online and self.online_meeting_url:
            d["online_meeting_url"] = self.online_meeting_url
        if self.attendees:
            d["attendees"] = [{"name": a.get("name"), "email": a.get("email")} for a in self.attendees]
        return d


@dataclass
class Calendar:
    """Represents a calendar."""
    id: str
    name: str
    color: Optional[str] = None
    is_default: bool = False
    can_edit: bool = True
    can_share: bool = True
    owner: Optional[Dict] = None


class OutlookCalendarConnector:
    """
    Microsoft Outlook Calendar connector via Graph API.
    
    Provides full calendar functionality:
    - List, search, create, update, delete events
    - Recurring event support
    - Find free/busy times
    - Multiple calendar support
    - Meeting invitations with attendees
    """
    
    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()
        self._connected = False
        self._timezone = "UTC"
    
    async def connect(self) -> bool:
        """Connect to Outlook Calendar via Microsoft Graph API."""
        if not self._client.connected:
            success = await self._client.connect(['calendar'])
            if not success:
                return False
        
        # Get user's timezone setting
        try:
            settings = await self._client.get("/me/mailboxSettings", scopes=['calendar'])
            self._timezone = settings.get('timeZone', 'UTC')
            self._connected = True
            return True
        except GraphAPIError:
            # Default to UTC if we can't get settings
            self._timezone = "UTC"
            self._connected = True
            return True
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @property
    def timezone(self) -> str:
        return self._timezone
    
    def _parse_datetime(self, dt_dict: Dict) -> Optional[datetime]:
        """Parse Graph API datetime dict."""
        if not dt_dict:
            return None
        
        dt_str = dt_dict.get('dateTime', '')
        try:
            # Graph returns ISO format without timezone offset
            if 'T' in dt_str:
                return datetime.fromisoformat(dt_str.replace('Z', ''))
            return datetime.fromisoformat(dt_str)
        except:
            return None
    
    def _format_datetime(self, dt: datetime) -> Dict:
        """Format datetime for Graph API."""
        return {
            "dateTime": dt.isoformat(),
            "timeZone": self._timezone,
        }
    
    def _parse_event(self, event: Dict) -> CalendarEvent:
        """Parse Graph API event into CalendarEvent."""
        organizer = event.get('organizer', {}).get('emailAddress', {})
        
        attendees = []
        for att in event.get('attendees', []):
            email_addr = att.get('emailAddress', {})
            status = att.get('status', {})
            attendees.append({
                'name': email_addr.get('name', ''),
                'email': email_addr.get('address', ''),
                'type': att.get('type', 'required'),
                'response': status.get('response', 'none'),
            })
        
        location = event.get('location', {})
        loc_str = location.get('displayName', '') if location else ''
        
        body = event.get('body', {})
        description = body.get('content', '') if body else ''
        
        online_meeting = event.get('onlineMeeting', {})
        
        return CalendarEvent(
            id=event.get('id', ''),
            subject=event.get('subject', '(No Subject)'),
            start=self._parse_datetime(event.get('start')),
            end=self._parse_datetime(event.get('end')),
            location=loc_str,
            description=description,
            is_all_day=event.get('isAllDay', False),
            is_online=bool(online_meeting),
            online_meeting_url=online_meeting.get('joinUrl') if online_meeting else None,
            organizer={
                'name': organizer.get('name', ''),
                'email': organizer.get('address', ''),
            },
            attendees=attendees,
            is_cancelled=event.get('isCancelled', False),
            is_recurring=event.get('type') == 'occurrence' or event.get('recurrence') is not None,
            recurrence=event.get('recurrence'),
            reminder_minutes=event.get('reminderMinutesBeforeStart', 15),
            show_as=event.get('showAs', 'busy'),
            importance=event.get('importance', 'normal'),
            sensitivity=event.get('sensitivity', 'normal'),
            web_link=event.get('webLink'),
            categories=event.get('categories', []),
        )
    
    async def list_calendars(self) -> List[Calendar]:
        """List all calendars."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self._client.get("/me/calendars", scopes=['calendar'])
        
        return [
            Calendar(
                id=c.get('id'),
                name=c.get('name'),
                color=c.get('color'),
                is_default=c.get('isDefaultCalendar', False),
                can_edit=c.get('canEdit', True),
                can_share=c.get('canShare', True),
                owner=c.get('owner'),
            )
            for c in result.get('value', [])
        ]
    
    async def list_events(
        self,
        calendar_id: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        max_results: int = 50,
    ) -> List[CalendarEvent]:
        """
        List calendar events.
        
        Args:
            calendar_id: Calendar ID (None for default calendar)
            start_time: Filter events starting after this time
            end_time: Filter events ending before this time
            max_results: Maximum events to return
        
        Returns:
            List of CalendarEvent objects
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Default to next 30 days
        if not start_time:
            start_time = datetime.now()
        if not end_time:
            end_time = start_time + timedelta(days=30)
        
        if calendar_id:
            endpoint = f"/me/calendars/{calendar_id}/calendarView"
        else:
            endpoint = "/me/calendarView"
        
        params = {
            'startDateTime': start_time.isoformat(),
            'endDateTime': end_time.isoformat(),
            '$top': max_results,
            '$orderby': 'start/dateTime',
            '$select': 'id,subject,start,end,location,isAllDay,organizer,'
                      'attendees,isCancelled,recurrence,reminderMinutesBeforeStart,'
                      'showAs,importance,sensitivity,webLink,categories,'
                      'onlineMeeting,type',
        }
        
        result = await self._client.get(endpoint, params=params, scopes=['calendar'])
        return [self._parse_event(e) for e in result.get('value', [])]
    
    async def get_event(self, event_id: str) -> CalendarEvent:
        """Get a single event with full details."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self._client.get(f"/me/events/{event_id}", scopes=['calendar'])
        return self._parse_event(result)
    
    async def search_events(
        self,
        query: str,
        start_time: datetime = None,
        end_time: datetime = None,
        max_results: int = 25,
    ) -> List[CalendarEvent]:
        """
        Search calendar events.
        
        Args:
            query: Search query (searches subject, body, location)
            start_time: Search from this time
            end_time: Search until this time
            max_results: Maximum results
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not start_time:
            start_time = datetime.now() - timedelta(days=30)
        if not end_time:
            end_time = datetime.now() + timedelta(days=365)
        
        params = {
            'startDateTime': start_time.isoformat(),
            'endDateTime': end_time.isoformat(),
            '$top': max_results,
            '$filter': f"contains(subject, '{query}') or contains(body/content, '{query}')",
        }
        
        result = await self._client.get("/me/calendarView", params=params, scopes=['calendar'])
        return [self._parse_event(e) for e in result.get('value', [])]
    
    async def create_event(
        self,
        subject: str,
        start: datetime,
        end: datetime,
        location: str = None,
        description: str = None,
        attendees: List[str] = None,
        is_all_day: bool = False,
        is_online_meeting: bool = False,
        reminder_minutes: int = 15,
        show_as: str = "busy",
        importance: str = "normal",
        calendar_id: str = None,
        recurrence: Dict = None,
    ) -> CalendarEvent:
        """
        Create a calendar event.
        
        Args:
            subject: Event title
            start: Start datetime
            end: End datetime
            location: Location string
            description: Event description/body
            attendees: List of attendee email addresses
            is_all_day: All-day event
            is_online_meeting: Create Teams meeting
            reminder_minutes: Minutes before to remind
            show_as: free, tentative, busy, oof, workingElsewhere
            importance: low, normal, high
            calendar_id: Calendar to create in (None for default)
            recurrence: Recurrence pattern dict
        
        Returns:
            Created CalendarEvent
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        event = {
            "subject": subject,
            "start": self._format_datetime(start),
            "end": self._format_datetime(end),
            "isAllDay": is_all_day,
            "reminderMinutesBeforeStart": reminder_minutes,
            "showAs": show_as,
            "importance": importance,
        }
        
        if location:
            event["location"] = {"displayName": location}
        
        if description:
            event["body"] = {
                "contentType": "HTML",
                "content": description,
            }
        
        if attendees:
            event["attendees"] = [
                {
                    "emailAddress": {"address": email.strip()},
                    "type": "required",
                }
                for email in attendees
            ]
        
        if is_online_meeting:
            event["isOnlineMeeting"] = True
            event["onlineMeetingProvider"] = "teamsForBusiness"
        
        if recurrence:
            event["recurrence"] = recurrence
        
        if calendar_id:
            endpoint = f"/me/calendars/{calendar_id}/events"
        else:
            endpoint = "/me/events"
        
        result = await self._client.post(endpoint, json_data=event, scopes=['calendar'])
        return self._parse_event(result)
    
    async def update_event(
        self,
        event_id: str,
        subject: str = None,
        start: datetime = None,
        end: datetime = None,
        location: str = None,
        description: str = None,
        attendees: List[str] = None,
        reminder_minutes: int = None,
    ) -> CalendarEvent:
        """
        Update an existing event.
        
        Only provided fields are updated.
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        update = {}
        
        if subject is not None:
            update["subject"] = subject
        if start is not None:
            update["start"] = self._format_datetime(start)
        if end is not None:
            update["end"] = self._format_datetime(end)
        if location is not None:
            update["location"] = {"displayName": location}
        if description is not None:
            update["body"] = {"contentType": "HTML", "content": description}
        if reminder_minutes is not None:
            update["reminderMinutesBeforeStart"] = reminder_minutes
        if attendees is not None:
            update["attendees"] = [
                {"emailAddress": {"address": email.strip()}, "type": "required"}
                for email in attendees
            ]
        
        result = await self._client.patch(
            f"/me/events/{event_id}",
            json_data=update,
            scopes=['calendar'],
        )
        return self._parse_event(result)
    
    async def delete_event(self, event_id: str) -> bool:
        """Delete a calendar event."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        await self._client.delete(f"/me/events/{event_id}", scopes=['calendar'])
        return True
    
    async def respond_to_event(
        self,
        event_id: str,
        response: str,  # accept, tentativelyAccept, decline
        comment: str = None,
        send_response: bool = True,
    ) -> bool:
        """
        Respond to a meeting invitation.
        
        Args:
            event_id: Event ID
            response: accept, tentativelyAccept, or decline
            comment: Optional comment to organizer
            send_response: Whether to send response to organizer
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if response not in ['accept', 'tentativelyAccept', 'decline']:
            raise ValueError(f"Invalid response: {response}")
        
        body = {"sendResponse": send_response}
        if comment:
            body["comment"] = comment
        
        await self._client.post(
            f"/me/events/{event_id}/{response}",
            json_data=body,
            scopes=['calendar'],
        )
        return True
    
    async def find_free_time(
        self,
        attendees: List[str],
        duration_minutes: int = 60,
        start_time: datetime = None,
        end_time: datetime = None,
        meeting_interval: int = 30,
    ) -> List[Dict]:
        """
        Find available meeting times.
        
        Uses findMeetingTimes API to find slots where all attendees are free.
        
        Args:
            attendees: List of email addresses
            duration_minutes: Meeting duration
            start_time: Search from (default: now)
            end_time: Search until (default: 7 days from start)
            meeting_interval: Slot interval in minutes
        
        Returns:
            List of suggested meeting times
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if not start_time:
            start_time = datetime.now()
        if not end_time:
            end_time = start_time + timedelta(days=7)
        
        request = {
            "attendees": [
                {"emailAddress": {"address": email}, "type": "required"}
                for email in attendees
            ],
            "timeConstraint": {
                "activityDomain": "work",
                "timeslots": [
                    {
                        "start": self._format_datetime(start_time),
                        "end": self._format_datetime(end_time),
                    }
                ],
            },
            "meetingDuration": f"PT{duration_minutes}M",
            "returnSuggestionReasons": True,
            "minimumAttendeePercentage": 100,
        }
        
        result = await self._client.post(
            "/me/findMeetingTimes",
            json_data=request,
            scopes=['calendar'],
        )
        
        suggestions = []
        for suggestion in result.get('meetingTimeSuggestions', []):
            time_slot = suggestion.get('meetingTimeSlot', {})
            suggestions.append({
                'start': self._parse_datetime(time_slot.get('start')),
                'end': self._parse_datetime(time_slot.get('end')),
                'confidence': suggestion.get('confidence', 0),
                'organizer_availability': suggestion.get('organizerAvailability'),
                'attendee_availability': [
                    {
                        'email': a.get('attendee', {}).get('emailAddress', {}).get('address'),
                        'availability': a.get('availability'),
                    }
                    for a in suggestion.get('attendeeAvailability', [])
                ],
            })
        
        return suggestions
    
    async def get_free_busy(
        self,
        schedules: List[str],
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, List[Dict]]:
        """
        Get free/busy information for multiple users.
        
        Args:
            schedules: List of email addresses
            start_time: Start of time range
            end_time: End of time range
        
        Returns:
            Dict mapping email to list of busy times
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = {
            "schedules": schedules,
            "startTime": self._format_datetime(start_time),
            "endTime": self._format_datetime(end_time),
            "availabilityViewInterval": 30,  # 30 minute intervals
        }
        
        result = await self._client.post(
            "/me/calendar/getSchedule",
            json_data=request,
            scopes=['calendar'],
        )
        
        free_busy = {}
        for schedule in result.get('value', []):
            email = schedule.get('scheduleId', '')
            busy_times = []
            for item in schedule.get('scheduleItems', []):
                busy_times.append({
                    'status': item.get('status'),
                    'start': self._parse_datetime(item.get('start')),
                    'end': self._parse_datetime(item.get('end')),
                    'subject': item.get('subject'),
                    'location': item.get('location'),
                })
            free_busy[email] = busy_times
        
        return free_busy


# Recurrence pattern helpers
def daily_recurrence(interval: int = 1, count: int = None, end_date: datetime = None) -> Dict:
    """Create daily recurrence pattern."""
    pattern = {
        "pattern": {
            "type": "daily",
            "interval": interval,
        },
        "range": _recurrence_range(count, end_date),
    }
    return pattern


def weekly_recurrence(
    days: List[str],  # e.g., ["monday", "wednesday", "friday"]
    interval: int = 1,
    count: int = None,
    end_date: datetime = None,
) -> Dict:
    """Create weekly recurrence pattern."""
    return {
        "pattern": {
            "type": "weekly",
            "interval": interval,
            "daysOfWeek": days,
            "firstDayOfWeek": "sunday",
        },
        "range": _recurrence_range(count, end_date),
    }


def monthly_recurrence(
    day_of_month: int,
    interval: int = 1,
    count: int = None,
    end_date: datetime = None,
) -> Dict:
    """Create monthly recurrence pattern (specific day of month)."""
    return {
        "pattern": {
            "type": "absoluteMonthly",
            "interval": interval,
            "dayOfMonth": day_of_month,
        },
        "range": _recurrence_range(count, end_date),
    }


def _recurrence_range(count: int = None, end_date: datetime = None) -> Dict:
    """Build recurrence range."""
    if count:
        return {"type": "numbered", "numberOfOccurrences": count}
    elif end_date:
        return {"type": "endDate", "endDate": end_date.strftime("%Y-%m-%d")}
    else:
        return {"type": "noEnd"}
