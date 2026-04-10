"""Telic Engine Primitives Package"""

from .base import StepResult, Primitive, get_data_index, set_data_index

from .system import FilePrimitive, ShellPrimitive, ClipboardPrimitive, ScreenshotPrimitive, AutomationPrimitive, SearchPrimitive, NotifyPrimitive
from .data import DocumentPrimitive, ComputePrimitive, DataPrimitive, DatabasePrimitive, TranslatePrimitive, KnowledgePrimitive, PatternsPrimitive, IntelligencePrimitive
from .communication import EmailPrimitive, ContactsPrimitive, MessagePrimitive, SmsPrimitive, TelegramPrimitive, SocialPrimitive
from .productivity import CalendarPrimitive, TaskPrimitive, NotesPrimitive, SpreadsheetPrimitive, PresentationPrimitive
from .web import WebPrimitive, BrowserPrimitive, WeatherPrimitive, NewsPrimitive, MediaPrimitive, PhotoPrimitive
from .services import NotionPrimitive, LinearPrimitive, TrelloPrimitive, AirtablePrimitive, ZoomPrimitive, LinkedInPrimitive, RedditPrimitive, HubSpotPrimitive, StripePrimitive, DevToolsPrimitive, CloudStoragePrimitive
from .lifestyle import FinancePrimitive, HomePrimitive, ShoppingPrimitive
from .skills import PhotoBookSkill, ReportSkill, DataVizSkill, FileConverterSkill, ExpenseReportSkill, PresentationBuilderSkill, InvoiceSkill, MeetingPrepSkill, TravelItinerarySkill, SocialMediaKitSkill

__all__ = [
    "StepResult", "Primitive", "get_data_index", "set_data_index",
    "FilePrimitive",
    "ShellPrimitive",
    "ClipboardPrimitive",
    "ScreenshotPrimitive",
    "AutomationPrimitive",
    "SearchPrimitive",
    "NotifyPrimitive",
    "DocumentPrimitive",
    "ComputePrimitive",
    "DataPrimitive",
    "DatabasePrimitive",
    "TranslatePrimitive",
    "KnowledgePrimitive",
    "PatternsPrimitive",
    "IntelligencePrimitive",
    "EmailPrimitive",
    "ContactsPrimitive",
    "MessagePrimitive",
    "SmsPrimitive",
    "TelegramPrimitive",
    "SocialPrimitive",
    "CalendarPrimitive",
    "TaskPrimitive",
    "NotesPrimitive",
    "SpreadsheetPrimitive",
    "PresentationPrimitive",
    "WebPrimitive",
    "BrowserPrimitive",
    "WeatherPrimitive",
    "NewsPrimitive",
    "MediaPrimitive",
    "PhotoPrimitive",
    "NotionPrimitive",
    "LinearPrimitive",
    "TrelloPrimitive",
    "AirtablePrimitive",
    "ZoomPrimitive",
    "LinkedInPrimitive",
    "RedditPrimitive",
    "HubSpotPrimitive",
    "StripePrimitive",
    "DevToolsPrimitive",
    "CloudStoragePrimitive",
    "FinancePrimitive",
    "HomePrimitive",
    "ShoppingPrimitive",
    "PhotoBookSkill",
    "ReportSkill",
    "DataVizSkill",
    "FileConverterSkill",
    "ExpenseReportSkill",
    "PresentationBuilderSkill",
    "InvoiceSkill",
    "MeetingPrepSkill",
    "TravelItinerarySkill",
    "SocialMediaKitSkill",
]
