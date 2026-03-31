"""
Service Connectors for Apex Integration Platform

Real integrations with external services:
- Google Suite (Gmail, Calendar, Drive)
- More coming (Notion, Slack, GitHub, etc.)
"""

from .google import (
    GmailConnector,
    GoogleCalendarConnector, 
    GoogleDriveConnector,
    Email,
    CalendarEvent,
    DriveFile,
    get_gmail_connector,
    get_calendar_connector,
    get_drive_connector,
)

__all__ = [
    # Google connectors
    "GmailConnector",
    "GoogleCalendarConnector",
    "GoogleDriveConnector",
    "Email",
    "CalendarEvent", 
    "DriveFile",
    "get_gmail_connector",
    "get_calendar_connector",
    "get_drive_connector",
]
