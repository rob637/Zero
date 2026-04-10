"""
Telic Engine - Phase 1 Implementation

This is the WORKING implementation that ties everything together.

Usage:
    from apex_engine import Apex
    
    engine = Apex(api_key="...")
    
    # Simple request
    result = await engine.do("Find all PDFs in Downloads and list them")
    
    # With context
    result = await engine.do(
        "Create an amortization schedule from this loan and email it to Fred",
        context={"loan_doc": "~/Documents/loan.pdf"}
    )
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# LLM client (lazy-loaded for fast startup)
_litellm = None
def _get_litellm():
    global _litellm
    if _litellm is None:
        try:
            import litellm
            _litellm = litellm
        except ImportError:
            pass
    return _litellm

# Safety rails
try:
    from src.privacy.redaction import RedactionEngine
    from src.privacy.audit_log import AuditLogger, TransmissionDestination
    from src.control.trust_levels import TrustLevel, TrustLevelManager
    from src.control.approval_gateway import ApprovalGateway, RiskLevel
    from src.control.undo_manager import UndoManager, UndoType
    from src.control.action_history import ActionHistoryDB, ActionCategory
    HAS_SAFETY_RAILS = True
except ImportError:
    HAS_SAFETY_RAILS = False

logger = logging.getLogger(__name__)

# Re-export from primitives package for backward compatibility
from primitives import (
    StepResult, Primitive, get_data_index, set_data_index,
    # System & Utility
    FilePrimitive, ShellPrimitive, ClipboardPrimitive, ScreenshotPrimitive, AutomationPrimitive, SearchPrimitive, NotifyPrimitive,
    # Data & Knowledge
    DocumentPrimitive, ComputePrimitive, DataPrimitive, DatabasePrimitive, TranslatePrimitive, KnowledgePrimitive, PatternsPrimitive, IntelligencePrimitive,
    # Communication
    EmailPrimitive, ContactsPrimitive, MessagePrimitive, SmsPrimitive, TelegramPrimitive, SocialPrimitive,
    # Productivity
    CalendarPrimitive, TaskPrimitive, NotesPrimitive, SpreadsheetPrimitive, PresentationPrimitive,
    # Web & Media
    WebPrimitive, BrowserPrimitive, WeatherPrimitive, NewsPrimitive, MediaPrimitive, PhotoPrimitive,
    # Third-Party Services
    NotionPrimitive, LinearPrimitive, TrelloPrimitive, AirtablePrimitive, ZoomPrimitive, LinkedInPrimitive, RedditPrimitive, HubSpotPrimitive, StripePrimitive, DevToolsPrimitive, CloudStoragePrimitive,
    # Creators — generic rendering primitives (PDF, PPTX, charts)
    PdfPrimitive, SlidesPrimitive, ChartPrimitive,
    # Lifestyle
    FinancePrimitive, HomePrimitive, ShoppingPrimitive,
)


class Apex:
    """
    The Telic Engine - unified interface to all capabilities.
    
    Usage:
        engine = Apex(api_key="...")
        result = await engine.do("Create amortization from loan doc and email to Fred")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        storage_path: Optional[str] = None,
        connectors: Optional[Dict[str, Any]] = None,
        enable_safety: bool = True,
    ):
        # Auto-detect API key and model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        
        # Auto-select model based on API key
        if model:
            self._model = model
        elif os.environ.get("ANTHROPIC_API_KEY") or (self._api_key and self._api_key.startswith("sk-ant-")):
            self._model = "anthropic/claude-sonnet-4-20250514"
        else:
            self._model = "gpt-4o-mini"
        self._storage_path = Path(storage_path or "~/.telic").expanduser()
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._connectors = connectors or {}
        
        # Safety rails
        self._safety_enabled = enable_safety and HAS_SAFETY_RAILS
        self._redaction: Optional[Any] = None
        self._audit: Optional[Any] = None
        self._trust: Optional[Any] = None
        self._approval: Optional[Any] = None
        self._undo: Optional[Any] = None
        self._action_history: Optional[Any] = None
        
        if self._safety_enabled:
            db_dir = str(self._storage_path / "db")
            Path(db_dir).mkdir(parents=True, exist_ok=True)
            self._redaction = RedactionEngine()
            self._audit = AuditLogger(db_path=os.path.join(db_dir, "audit.db"))
            self._trust = TrustLevelManager(db_path=os.path.join(db_dir, "trust.db"))
            self._approval = ApprovalGateway(trust_mgr=self._trust, audit_logger=self._audit)
            self._undo = UndoManager(db_path=os.path.join(db_dir, "undo.db"), backup_dir=str(self._storage_path / "undo_backups"))
            self._action_history = ActionHistoryDB(db_path=os.path.join(db_dir, "history.db"))
        
        # Initialize primitives
        self._primitives: Dict[str, Primitive] = {}
        self._init_primitives()
    
    @staticmethod
    def _follow_path_static(data: Any, path: str) -> Any:
        """Navigate into data via dot-path (static version for Orchestrator)."""
        for part in path.split('.'):
            if data is None:
                return None
            if isinstance(data, dict):
                data = data.get(part)
            elif isinstance(data, (list, tuple)):
                try:
                    data = data[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return data
    
    def _init_primitives(self):
        """Initialize all primitives, wiring in connectors as providers."""
        c = self._connectors
        
        self._primitives["FILE"] = FilePrimitive()
        self._primitives["DOCUMENT"] = DocumentPrimitive(self._llm_complete)
        self._primitives["COMPUTE"] = ComputePrimitive(self._llm_complete)
        
        # Email — wire Gmail and/or Outlook connectors
        email_providers = {}
        gmail = c.get("gmail")
        outlook = c.get("outlook")
        if gmail:
            email_providers["gmail"] = gmail
        if outlook:
            email_providers["outlook"] = outlook
        first_email = gmail or outlook
        self._primitives["EMAIL"] = EmailPrimitive(
            providers=email_providers,
            send_func=first_email.send_email if first_email else None,
            list_func=first_email.list_messages if first_email else None,
            read_func=first_email.get_message if first_email and hasattr(first_email, 'get_message') else None,
            connector=first_email,
        )
        
        # Contacts — wire Google Contacts and/or Microsoft Contacts
        contacts_providers = {}
        if c.get("contacts"):
            contacts_providers["google"] = c["contacts"]
        if c.get("contacts_microsoft"):
            contacts_providers["microsoft"] = c["contacts_microsoft"]
        self._primitives["CONTACTS"] = ContactsPrimitive(providers=contacts_providers)
        
        self._primitives["KNOWLEDGE"] = KnowledgePrimitive(str(self._storage_path / "knowledge.json"))
        self._primitives["PATTERNS"] = PatternsPrimitive()
        self._primitives["INTELLIGENCE"] = IntelligencePrimitive()
        
        # Calendar — wire Google Calendar and/or Outlook Calendar
        cal_providers = {}
        gcal = c.get("calendar")
        ocal = c.get("outlook_calendar")
        if gcal:
            cal_providers["google_calendar"] = gcal
        if ocal:
            cal_providers["outlook_calendar"] = ocal
        first_cal = gcal or ocal
        self._primitives["CALENDAR"] = CalendarPrimitive(
            str(self._storage_path / "calendar.json"),
            create_func=first_cal.create_event if first_cal else None,
            list_func=first_cal.list_events if first_cal else None,
            list_calendars_func=first_cal.list_calendars if first_cal and hasattr(first_cal, 'list_calendars') else None,
            providers=cal_providers,
        )
        
        self._primitives["WEB"] = WebPrimitive(self._llm_complete, search_provider=c.get("web_search"))
        
        # Weather — wire OpenWeatherMap connector
        self._primitives["WEATHER"] = WeatherPrimitive(c.get("weather"))
        
        # News — wire NewsAPI connector
        self._primitives["NEWS"] = NewsPrimitive(c.get("news"))
        
        # Notion — wire Notion connector
        self._primitives["NOTION"] = NotionPrimitive(c.get("notion"))
        
        # Linear — wire Linear connector
        self._primitives["LINEAR"] = LinearPrimitive(c.get("linear"))
        
        # Trello — wire Trello connector
        self._primitives["TRELLO"] = TrelloPrimitive(c.get("trello"))
        
        # Airtable — wire Airtable connector
        self._primitives["AIRTABLE"] = AirtablePrimitive(c.get("airtable"))
        
        # Zoom — wire Zoom connector
        self._primitives["ZOOM"] = ZoomPrimitive(c.get("zoom"))
        
        # LinkedIn — wire LinkedIn connector
        self._primitives["LINKEDIN"] = LinkedInPrimitive(c.get("linkedin"))
        
        # Reddit — wire Reddit connector
        self._primitives["REDDIT"] = RedditPrimitive(c.get("reddit"))
        
        # Telegram — wire Telegram connector
        self._primitives["TELEGRAM"] = TelegramPrimitive(c.get("telegram"))
        
        # HubSpot — wire HubSpot connector
        self._primitives["HUBSPOT"] = HubSpotPrimitive(c.get("hubspot"))
        
        # Stripe — wire Stripe connector
        self._primitives["STRIPE"] = StripePrimitive(c.get("stripe"))
        
        # Notify — wire DesktopNotify connector
        notify_send = None
        desktop_notify = c.get("desktop_notify")
        if desktop_notify and hasattr(desktop_notify, "send"):
            notify_send = desktop_notify.send
        self._primitives["NOTIFY"] = NotifyPrimitive(str(self._storage_path / "reminders.json"), send_func=notify_send)
        
        # Task — wire Todoist, Microsoft To-Do, Jira
        task_providers = {}
        if c.get("todoist"):
            task_providers["todoist"] = c["todoist"]
        if c.get("microsoft_todo"):
            task_providers["microsoft_todo"] = c["microsoft_todo"]
        if c.get("jira"):
            task_providers["jira"] = c["jira"]
        self._primitives["TASK"] = TaskPrimitive(
            str(self._storage_path / "tasks.json"),
            providers=task_providers,
        )
        
        self._primitives["SHELL"] = ShellPrimitive()
        self._primitives["DATA"] = DataPrimitive(self._llm_complete)
        
        # Message — wire Slack, Teams, Discord, SMS
        msg_providers = {}
        if c.get("slack"):
            msg_providers["slack"] = c["slack"]
        if c.get("teams"):
            msg_providers["teams"] = c["teams"]
        if c.get("discord"):
            msg_providers["discord"] = c["discord"]
        if c.get("sms"):
            msg_providers["sms"] = c["sms"]
        self._primitives["MESSAGE"] = MessagePrimitive(providers=msg_providers)
        
        # Media — wire Spotify, YouTube
        media_providers = {}
        if c.get("spotify"):
            media_providers["spotify"] = c["spotify"]
        if c.get("youtube"):
            media_providers["youtube"] = c["youtube"]
        self._primitives["MEDIA"] = MediaPrimitive(self._llm_complete, providers=media_providers)
        
        self._primitives["BROWSER"] = BrowserPrimitive(self._llm_complete)
        
        # DevTools — wire GitHub, Jira
        devtools_providers = {}
        if c.get("github"):
            devtools_providers["github"] = c["github"]
        if c.get("jira"):
            devtools_providers["jira"] = c["jira"]
        if c.get("devtools"):
            devtools_providers["unified"] = c["devtools"]
        self._primitives["DEVTOOLS"] = DevToolsPrimitive(providers=devtools_providers)
        
        # Cloud Storage — wire Drive, OneDrive, Dropbox
        storage_providers = {}
        if c.get("drive"):
            storage_providers["google_drive"] = c["drive"]
        if c.get("onedrive"):
            storage_providers["onedrive"] = c["onedrive"]
        if c.get("dropbox"):
            storage_providers["dropbox"] = c["dropbox"]
        self._primitives["CLOUD_STORAGE"] = CloudStoragePrimitive(providers=storage_providers)
        
        # Clipboard — system clipboard operations
        self._primitives["CLIPBOARD"] = ClipboardPrimitive()
        
        # Translate — language translation via LLM
        self._primitives["TRANSLATE"] = TranslatePrimitive(self._llm_complete)
        
        # Database — SQLite database operations
        self._primitives["DATABASE"] = DatabasePrimitive(str(self._storage_path / "data.db"))
        
        # Screenshot — screen capture
        self._primitives["SCREENSHOT"] = ScreenshotPrimitive()
        
        # Automation — rules/triggers
        self._primitives["AUTOMATION"] = AutomationPrimitive(str(self._storage_path / "automations.json"))
        
        # Search — unified search across all primitives
        self._primitives["SEARCH"] = SearchPrimitive(self._primitives)
        
        # CHAT removed — duplicates MESSAGE (same providers: Slack, Teams, Discord)
        # MEETING removed — duplicates ZOOM (which has deeper Zoom API integration)
        
        # SMS — text messaging
        sms_providers = {}
        if c.get("twilio"):
            sms_providers["twilio"] = c["twilio"]
        if c.get("sms"):
            sms_providers["sms"] = c["sms"]
        self._primitives["SMS"] = SmsPrimitive(providers=sms_providers)
        
        # Spreadsheet — Excel, Google Sheets
        spreadsheet_providers = {}
        if c.get("google_sheets"):
            spreadsheet_providers["google_sheets"] = c["google_sheets"]
        if c.get("excel"):
            spreadsheet_providers["excel"] = c["excel"]
        self._primitives["SPREADSHEET"] = SpreadsheetPrimitive(self._llm_complete, providers=spreadsheet_providers)
        
        # Presentation — PowerPoint, Google Slides
        presentation_providers = {}
        if c.get("google_slides"):
            presentation_providers["google_slides"] = c["google_slides"]
        if c.get("powerpoint"):
            presentation_providers["powerpoint"] = c["powerpoint"]
        self._primitives["PRESENTATION"] = PresentationPrimitive(self._llm_complete, providers=presentation_providers)
        
        # Notes — OneNote, Apple Notes, Google Keep
        notes_providers = {}
        if c.get("onenote"):
            notes_providers["onenote"] = c["onenote"]
        if c.get("google_keep"):
            notes_providers["google_keep"] = c["google_keep"]
        self._primitives["NOTES"] = NotesPrimitive(str(self._storage_path / "notes"), providers=notes_providers)
        
        # Finance — wire Stripe for payment/invoice operations
        finance_providers = {}
        if c.get("stripe"):
            finance_providers["stripe"] = c["stripe"]
        self._primitives["FINANCE"] = FinancePrimitive(providers=finance_providers)
        
        # Home — wire SmartThings for smart home control
        home_providers = {}
        if c.get("smartthings"):
            home_providers["smartthings"] = c["smartthings"]
        self._primitives["HOME"] = HomePrimitive(providers=home_providers)
        
        # Shopping — wire eBay for product search/orders
        shopping_providers = {}
        if c.get("ebay"):
            shopping_providers["ebay"] = c["ebay"]
        self._primitives["SHOPPING"] = ShoppingPrimitive(providers=shopping_providers)
        
        # REMOVED: RIDE, TRAVEL primitives — no viable public APIs exist
        
        # Social — Twitter, LinkedIn, Facebook
        social_providers = {}
        if c.get("twitter"):
            social_providers["twitter"] = c["twitter"]
        if c.get("linkedin"):
            social_providers["linkedin"] = c["linkedin"]
        if c.get("facebook"):
            social_providers["facebook"] = c["facebook"]
        self._primitives["SOCIAL"] = SocialPrimitive(providers=social_providers)
        
        # Photo — Google Photos, iCloud
        photo_providers = {}
        if c.get("google_photos"):
            photo_providers["google_photos"] = c["google_photos"]
        if c.get("icloud_photos"):
            photo_providers["icloud_photos"] = c["icloud_photos"]
        self._primitives["PHOTO"] = PhotoPrimitive(providers=photo_providers)
        
        # Creators — generic rendering primitives (LLM decides content, these just render)
        self._primitives["PDF"] = PdfPrimitive()
        self._primitives["SLIDES"] = SlidesPrimitive()
        self._primitives["CHART"] = ChartPrimitive()
    
    async def _llm_complete(self, prompt: str, triggering_request: str = "") -> str:
        """Call LLM for completion — with PII redaction and audit logging when safety is enabled."""
        if not self._api_key:
            raise ValueError("No API key configured. Set OPENAI_API_KEY or pass api_key to the engine")
        
        # Redact PII before sending to LLM
        send_prompt = prompt
        redaction_count = 0
        if self._safety_enabled and self._redaction:
            redaction_result = self._redaction.redact(prompt)
            send_prompt = redaction_result.redacted_text
            redaction_count = redaction_result.redaction_count
        
        # Log outbound transmission
        request_id = str(uuid.uuid4())[:8]
        if self._safety_enabled and self._audit:
            dest = TransmissionDestination.OPENAI if "gpt" in self._model else TransmissionDestination.ANTHROPIC
            self._audit.log_outbound(
                destination=dest,
                content=send_prompt[:500],
                triggering_request=triggering_request or "engine_call",
                model=self._model,
                request_id=request_id,
                contained_pii=redaction_count > 0,
                redactions_applied=redaction_count,
            )
        
        _ll = _get_litellm()
        if _ll:
            response = await asyncio.to_thread(
                _ll.completion,
                model=self._model,
                messages=[{"role": "user", "content": send_prompt}],
                api_key=self._api_key,
            )
            result_text = response.choices[0].message.content
        else:
            # Fallback to direct OpenAI
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self._model, "messages": [{"role": "user", "content": send_prompt}]},
                    timeout=60,
                )
                result_text = resp.json()["choices"][0]["message"]["content"]
        
        # Log inbound response
        if self._safety_enabled and self._audit:
            self._audit.log_inbound(
                destination=dest,
                content=result_text[:500],
                request_id=request_id,
                model=self._model,
            )
        
        return result_text
    

