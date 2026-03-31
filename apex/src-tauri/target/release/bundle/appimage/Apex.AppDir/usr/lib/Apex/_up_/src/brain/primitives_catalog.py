"""
Apex Universal Primitives - Complete Capability Set

This defines ALL primitives needed to work with:
- Microsoft 365 (Outlook, Calendar, OneDrive, Teams, Word, Excel, PowerPoint, OneNote, To-Do)
- Google Workspace (Gmail, Calendar, Drive, Docs, Sheets, Slides, Keep, Tasks, Meet, Chat)
- Apple (Mail, Calendar, Notes, Reminders, iCloud Drive, Messages)
- Social (LinkedIn, Twitter/X, Facebook, Instagram)
- Finance (Banks, Quicken, Mint, PayPal, Venmo)
- Development (GitHub, GitLab, Jira, Slack)
- Local System (Files, Apps, Browser, Clipboard)
- Media (Spotify, Photos, YouTube)
- Communication (SMS, WhatsApp, Discord, Telegram)
- E-commerce (Amazon, eBay)
- Travel (Uber, Lyft, airlines, hotels)
- Smart Home (Alexa, Google Home, HomeKit)

Architecture:
    Each primitive is provider-agnostic.
    Connectors implement the provider-specific details.
    
    Example:
        EMAIL.send() works for:
        - Gmail (via GmailConnector)
        - Outlook (via OutlookConnector)  
        - Apple Mail (via AppleMailConnector)
        - Yahoo (via YahooMailConnector)

~25 Primitives × ~5 Operations = ~125 Atomic Capabilities
These 125 capabilities can compose into MILLIONS of workflows.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


# ============================================================
#  PRIMITIVE DEFINITIONS
# ============================================================

@dataclass
class PrimitiveDefinition:
    """Definition of a primitive capability."""
    name: str
    description: str
    operations: List[Dict[str, Any]]
    providers: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "operations": self.operations,
            "providers": self.providers,
        }


# ============================================================
#  COMPLETE PRIMITIVE CATALOG
# ============================================================

PRIMITIVES = {
    
    # ========================================
    #  COMMUNICATION
    # ========================================
    
    "EMAIL": PrimitiveDefinition(
        name="EMAIL",
        description="Email operations across all providers",
        operations=[
            {"name": "send", "params": ["to", "subject", "body", "cc?", "bcc?", "attachments?"], "description": "Send an email"},
            {"name": "draft", "params": ["to", "subject", "body"], "description": "Create a draft"},
            {"name": "reply", "params": ["message_id", "body"], "description": "Reply to an email"},
            {"name": "forward", "params": ["message_id", "to"], "description": "Forward an email"},
            {"name": "search", "params": ["query", "limit?"], "description": "Search emails"},
            {"name": "read", "params": ["message_id"], "description": "Read email content"},
            {"name": "list", "params": ["folder?", "limit?", "unread_only?"], "description": "List emails"},
            {"name": "move", "params": ["message_id", "folder"], "description": "Move to folder"},
            {"name": "delete", "params": ["message_id"], "description": "Delete email"},
            {"name": "label", "params": ["message_id", "labels"], "description": "Add labels/categories"},
            {"name": "archive", "params": ["message_id"], "description": "Archive email"},
        ],
        providers=["gmail", "outlook", "apple_mail", "yahoo", "protonmail"],
    ),
    
    "CHAT": PrimitiveDefinition(
        name="CHAT",
        description="Instant messaging operations",
        operations=[
            {"name": "send", "params": ["channel", "message", "attachments?"], "description": "Send a message"},
            {"name": "read", "params": ["channel", "limit?"], "description": "Read messages"},
            {"name": "search", "params": ["query", "channel?"], "description": "Search messages"},
            {"name": "react", "params": ["message_id", "emoji"], "description": "Add reaction"},
            {"name": "reply", "params": ["message_id", "text"], "description": "Reply in thread"},
            {"name": "list_channels", "params": [], "description": "List available channels"},
            {"name": "create_channel", "params": ["name", "members?"], "description": "Create channel"},
        ],
        providers=["slack", "teams", "discord", "telegram", "whatsapp", "imessage", "google_chat"],
    ),
    
    "MEETING": PrimitiveDefinition(
        name="MEETING",
        description="Video conferencing operations",
        operations=[
            {"name": "schedule", "params": ["title", "start", "end", "attendees", "description?"], "description": "Schedule a meeting"},
            {"name": "join", "params": ["meeting_id"], "description": "Get join link"},
            {"name": "cancel", "params": ["meeting_id"], "description": "Cancel meeting"},
            {"name": "get_recording", "params": ["meeting_id"], "description": "Get recording"},
            {"name": "list_upcoming", "params": ["limit?"], "description": "List upcoming meetings"},
            {"name": "get_transcript", "params": ["meeting_id"], "description": "Get transcript"},
        ],
        providers=["zoom", "teams", "google_meet", "webex"],
    ),
    
    "SMS": PrimitiveDefinition(
        name="SMS",
        description="Text messaging",
        operations=[
            {"name": "send", "params": ["to", "message"], "description": "Send text message"},
            {"name": "read", "params": ["from?", "limit?"], "description": "Read messages"},
            {"name": "search", "params": ["query"], "description": "Search messages"},
        ],
        providers=["twilio", "imessage", "android_messages"],
    ),
    
    # ========================================
    #  CALENDAR & SCHEDULING
    # ========================================
    
    "CALENDAR": PrimitiveDefinition(
        name="CALENDAR",
        description="Calendar and scheduling operations",
        operations=[
            {"name": "list", "params": ["start?", "end?", "limit?"], "description": "List events"},
            {"name": "get", "params": ["event_id"], "description": "Get event details"},
            {"name": "create", "params": ["title", "start", "end", "description?", "location?", "attendees?"], "description": "Create event"},
            {"name": "update", "params": ["event_id", "title?", "start?", "end?"], "description": "Update event"},
            {"name": "delete", "params": ["event_id"], "description": "Delete event"},
            {"name": "rsvp", "params": ["event_id", "response"], "description": "Respond to invite"},
            {"name": "find_free_time", "params": ["attendees", "duration", "range_start", "range_end"], "description": "Find free time"},
            {"name": "list_calendars", "params": [], "description": "List all calendars"},
        ],
        providers=["google_calendar", "outlook_calendar", "apple_calendar"],
    ),
    
    "TASKS": PrimitiveDefinition(
        name="TASKS",
        description="Task and to-do management",
        operations=[
            {"name": "list", "params": ["list_id?", "status?"], "description": "List tasks"},
            {"name": "create", "params": ["title", "due_date?", "list_id?", "notes?", "priority?"], "description": "Create task"},
            {"name": "complete", "params": ["task_id"], "description": "Mark complete"},
            {"name": "update", "params": ["task_id", "title?", "due_date?", "priority?"], "description": "Update task"},
            {"name": "delete", "params": ["task_id"], "description": "Delete task"},
            {"name": "list_lists", "params": [], "description": "List task lists"},
            {"name": "create_list", "params": ["name"], "description": "Create task list"},
        ],
        providers=["google_tasks", "microsoft_todo", "todoist", "apple_reminders", "asana", "trello"],
    ),
    
    # ========================================
    #  FILES & STORAGE
    # ========================================
    
    "FILE": PrimitiveDefinition(
        name="FILE",
        description="Local file system operations",
        operations=[
            {"name": "read", "params": ["path"], "description": "Read file contents"},
            {"name": "write", "params": ["path", "content"], "description": "Write to file"},
            {"name": "search", "params": ["pattern", "directory?", "recursive?"], "description": "Search files"},
            {"name": "list", "params": ["directory"], "description": "List directory"},
            {"name": "move", "params": ["source", "destination"], "description": "Move/rename file"},
            {"name": "copy", "params": ["source", "destination"], "description": "Copy file"},
            {"name": "delete", "params": ["path"], "description": "Delete file"},
            {"name": "info", "params": ["path"], "description": "Get file metadata"},
            {"name": "zip", "params": ["paths", "output"], "description": "Create zip archive"},
            {"name": "unzip", "params": ["path", "destination"], "description": "Extract archive"},
        ],
        providers=["local"],
    ),
    
    "CLOUD_STORAGE": PrimitiveDefinition(
        name="CLOUD_STORAGE",
        description="Cloud storage operations",
        operations=[
            {"name": "list", "params": ["folder_id?", "limit?"], "description": "List files"},
            {"name": "upload", "params": ["local_path", "remote_path?", "folder_id?"], "description": "Upload file"},
            {"name": "download", "params": ["file_id", "local_path"], "description": "Download file"},
            {"name": "delete", "params": ["file_id"], "description": "Delete file"},
            {"name": "move", "params": ["file_id", "destination_folder"], "description": "Move file"},
            {"name": "share", "params": ["file_id", "email", "role?"], "description": "Share file"},
            {"name": "search", "params": ["query"], "description": "Search files"},
            {"name": "get_link", "params": ["file_id"], "description": "Get sharing link"},
            {"name": "create_folder", "params": ["name", "parent_id?"], "description": "Create folder"},
        ],
        providers=["google_drive", "onedrive", "dropbox", "icloud", "box"],
    ),
    
    # ========================================
    #  DOCUMENTS & PRODUCTIVITY
    # ========================================
    
    "DOCUMENT": PrimitiveDefinition(
        name="DOCUMENT",
        description="Document operations (parsing, creation, extraction)",
        operations=[
            {"name": "parse", "params": ["path_or_content", "format?"], "description": "Parse document to text"},
            {"name": "extract", "params": ["content", "schema"], "description": "Extract structured data (LLM)"},
            {"name": "create", "params": ["format", "content_or_data", "path?"], "description": "Create document"},
            {"name": "convert", "params": ["path", "to_format"], "description": "Convert format"},
            {"name": "summarize", "params": ["content", "max_length?"], "description": "Summarize content"},
            {"name": "translate", "params": ["content", "target_language"], "description": "Translate"},
            {"name": "ocr", "params": ["image_path"], "description": "Extract text from image"},
        ],
        providers=["local", "google_docs", "office_online"],
    ),
    
    "SPREADSHEET": PrimitiveDefinition(
        name="SPREADSHEET",
        description="Spreadsheet operations",
        operations=[
            {"name": "read", "params": ["file_id_or_path", "sheet?", "range?"], "description": "Read data"},
            {"name": "write", "params": ["file_id_or_path", "data", "sheet?", "range?"], "description": "Write data"},
            {"name": "create", "params": ["name", "data?"], "description": "Create spreadsheet"},
            {"name": "add_sheet", "params": ["file_id", "name"], "description": "Add worksheet"},
            {"name": "formula", "params": ["file_id", "cell", "formula"], "description": "Set formula"},
            {"name": "format", "params": ["file_id", "range", "format"], "description": "Format cells"},
            {"name": "chart", "params": ["file_id", "data_range", "chart_type"], "description": "Create chart"},
        ],
        providers=["google_sheets", "excel", "excel_online"],
    ),
    
    "PRESENTATION": PrimitiveDefinition(
        name="PRESENTATION",
        description="Presentation operations",
        operations=[
            {"name": "create", "params": ["name", "template?"], "description": "Create presentation"},
            {"name": "add_slide", "params": ["file_id", "layout?", "content?"], "description": "Add slide"},
            {"name": "update_slide", "params": ["file_id", "slide_id", "content"], "description": "Update slide"},
            {"name": "export", "params": ["file_id", "format"], "description": "Export to PDF/images"},
            {"name": "get_text", "params": ["file_id"], "description": "Extract all text"},
        ],
        providers=["google_slides", "powerpoint", "powerpoint_online"],
    ),
    
    "NOTES": PrimitiveDefinition(
        name="NOTES",
        description="Note-taking operations",
        operations=[
            {"name": "create", "params": ["title", "content", "folder?", "tags?"], "description": "Create note"},
            {"name": "read", "params": ["note_id"], "description": "Read note"},
            {"name": "update", "params": ["note_id", "content"], "description": "Update note"},
            {"name": "delete", "params": ["note_id"], "description": "Delete note"},
            {"name": "search", "params": ["query"], "description": "Search notes"},
            {"name": "list", "params": ["folder?"], "description": "List notes"},
            {"name": "add_attachment", "params": ["note_id", "file_path"], "description": "Add attachment"},
        ],
        providers=["google_keep", "onenote", "apple_notes", "notion", "evernote"],
    ),
    
    # ========================================
    #  PEOPLE & CONTACTS
    # ========================================
    
    "CONTACTS": PrimitiveDefinition(
        name="CONTACTS",
        description="Contact management",
        operations=[
            {"name": "search", "params": ["query"], "description": "Search contacts"},
            {"name": "get", "params": ["contact_id"], "description": "Get contact details"},
            {"name": "create", "params": ["name", "email?", "phone?", "company?"], "description": "Create contact"},
            {"name": "update", "params": ["contact_id", "fields"], "description": "Update contact"},
            {"name": "delete", "params": ["contact_id"], "description": "Delete contact"},
            {"name": "list", "params": ["group?", "limit?"], "description": "List contacts"},
            {"name": "add_to_group", "params": ["contact_id", "group"], "description": "Add to group"},
        ],
        providers=["google_contacts", "outlook_contacts", "apple_contacts", "linkedin"],
    ),
    
    # ========================================
    #  COMPUTE & DATA
    # ========================================
    
    "COMPUTE": PrimitiveDefinition(
        name="COMPUTE",
        description="Calculations and data processing",
        operations=[
            {"name": "formula", "params": ["name", "inputs"], "description": "Apply named formula"},
            {"name": "calculate", "params": ["expression", "variables?"], "description": "Evaluate expression"},
            {"name": "aggregate", "params": ["data", "function", "field?"], "description": "Aggregate data"},
            {"name": "transform", "params": ["data", "transformation"], "description": "Transform data"},
            {"name": "statistics", "params": ["data", "metrics"], "description": "Calculate statistics"},
            {"name": "compare", "params": ["data1", "data2"], "description": "Compare datasets"},
        ],
        providers=["local"],
    ),
    
    "KNOWLEDGE": PrimitiveDefinition(
        name="KNOWLEDGE",
        description="Memory and knowledge management",
        operations=[
            {"name": "remember", "params": ["content", "tags?"], "description": "Store information"},
            {"name": "recall", "params": ["query", "limit?"], "description": "Retrieve information"},
            {"name": "forget", "params": ["memory_id"], "description": "Remove information"},
            {"name": "search", "params": ["query", "filters?"], "description": "Search knowledge"},
            {"name": "relate", "params": ["item1", "item2", "relation"], "description": "Create relationship"},
            {"name": "get_related", "params": ["item", "relation?"], "description": "Get related items"},
        ],
        providers=["local"],
    ),
    
    # ========================================
    #  WEB & BROWSER
    # ========================================
    
    "WEB": PrimitiveDefinition(
        name="WEB",
        description="Web and browser operations",
        operations=[
            {"name": "fetch", "params": ["url"], "description": "Fetch webpage content"},
            {"name": "search", "params": ["query", "engine?"], "description": "Web search"},
            {"name": "screenshot", "params": ["url"], "description": "Take screenshot"},
            {"name": "extract", "params": ["url", "selector"], "description": "Extract specific elements"},
            {"name": "download", "params": ["url", "path"], "description": "Download file"},
            {"name": "open", "params": ["url"], "description": "Open in browser"},
        ],
        providers=["browser", "puppeteer"],
    ),
    
    # ========================================
    #  DEVELOPMENT
    # ========================================
    
    "CODE_REPO": PrimitiveDefinition(
        name="CODE_REPO",
        description="Code repository operations",
        operations=[
            {"name": "list_repos", "params": ["owner?"], "description": "List repositories"},
            {"name": "get_repo", "params": ["repo"], "description": "Get repo info"},
            {"name": "list_issues", "params": ["repo", "state?"], "description": "List issues"},
            {"name": "create_issue", "params": ["repo", "title", "body?", "labels?"], "description": "Create issue"},
            {"name": "list_prs", "params": ["repo", "state?"], "description": "List pull requests"},
            {"name": "create_pr", "params": ["repo", "title", "head", "base", "body?"], "description": "Create PR"},
            {"name": "get_file", "params": ["repo", "path", "ref?"], "description": "Get file content"},
            {"name": "commit", "params": ["repo", "path", "content", "message"], "description": "Commit change"},
        ],
        providers=["github", "gitlab", "bitbucket", "azure_devops"],
    ),
    
    "PROJECT": PrimitiveDefinition(
        name="PROJECT",
        description="Project management operations",
        operations=[
            {"name": "list_projects", "params": [], "description": "List projects"},
            {"name": "list_issues", "params": ["project", "status?", "assignee?"], "description": "List issues"},
            {"name": "create_issue", "params": ["project", "title", "description?", "type?", "priority?"], "description": "Create issue"},
            {"name": "update_issue", "params": ["issue_id", "fields"], "description": "Update issue"},
            {"name": "assign", "params": ["issue_id", "user"], "description": "Assign issue"},
            {"name": "transition", "params": ["issue_id", "status"], "description": "Change status"},
            {"name": "add_comment", "params": ["issue_id", "comment"], "description": "Add comment"},
        ],
        providers=["jira", "asana", "trello", "linear", "monday", "notion"],
    ),
    
    # ========================================
    #  FINANCE
    # ========================================
    
    "FINANCE": PrimitiveDefinition(
        name="FINANCE",
        description="Financial operations",
        operations=[
            {"name": "get_balance", "params": ["account?"], "description": "Get account balance"},
            {"name": "list_transactions", "params": ["account?", "start?", "end?", "limit?"], "description": "List transactions"},
            {"name": "categorize", "params": ["transaction_id", "category"], "description": "Categorize transaction"},
            {"name": "get_spending", "params": ["period", "category?"], "description": "Get spending summary"},
            {"name": "create_budget", "params": ["category", "amount", "period"], "description": "Create budget"},
            {"name": "send_payment", "params": ["to", "amount", "note?"], "description": "Send payment"},
            {"name": "request_payment", "params": ["from", "amount", "note?"], "description": "Request payment"},
        ],
        providers=["plaid", "mint", "quicken", "paypal", "venmo", "bank_api"],
    ),
    
    # ========================================
    #  SOCIAL
    # ========================================
    
    "SOCIAL": PrimitiveDefinition(
        name="SOCIAL",
        description="Social media operations",
        operations=[
            {"name": "post", "params": ["content", "media?"], "description": "Create post"},
            {"name": "get_feed", "params": ["limit?"], "description": "Get feed"},
            {"name": "search", "params": ["query"], "description": "Search posts"},
            {"name": "like", "params": ["post_id"], "description": "Like post"},
            {"name": "comment", "params": ["post_id", "text"], "description": "Comment on post"},
            {"name": "share", "params": ["post_id"], "description": "Share/repost"},
            {"name": "get_profile", "params": ["user_id?"], "description": "Get profile"},
            {"name": "get_notifications", "params": [], "description": "Get notifications"},
        ],
        providers=["twitter", "linkedin", "facebook", "instagram"],
    ),
    
    # ========================================
    #  MEDIA
    # ========================================
    
    "PHOTO": PrimitiveDefinition(
        name="PHOTO",
        description="Photo management operations",
        operations=[
            {"name": "list", "params": ["album?", "limit?"], "description": "List photos"},
            {"name": "upload", "params": ["path", "album?"], "description": "Upload photo"},
            {"name": "download", "params": ["photo_id", "path"], "description": "Download photo"},
            {"name": "search", "params": ["query"], "description": "Search photos"},
            {"name": "create_album", "params": ["name"], "description": "Create album"},
            {"name": "add_to_album", "params": ["photo_id", "album_id"], "description": "Add to album"},
            {"name": "get_metadata", "params": ["photo_id"], "description": "Get EXIF/metadata"},
            {"name": "edit", "params": ["photo_id", "operations"], "description": "Edit photo"},
        ],
        providers=["google_photos", "icloud_photos", "amazon_photos"],
    ),
    
    "MUSIC": PrimitiveDefinition(
        name="MUSIC",
        description="Music streaming operations",
        operations=[
            {"name": "play", "params": ["track?", "playlist?", "album?"], "description": "Play music"},
            {"name": "pause", "params": [], "description": "Pause playback"},
            {"name": "next", "params": [], "description": "Next track"},
            {"name": "search", "params": ["query"], "description": "Search music"},
            {"name": "add_to_playlist", "params": ["track_id", "playlist_id"], "description": "Add to playlist"},
            {"name": "create_playlist", "params": ["name", "tracks?"], "description": "Create playlist"},
            {"name": "get_playing", "params": [], "description": "Get current track"},
            {"name": "get_recommendations", "params": ["seed_track?"], "description": "Get recommendations"},
        ],
        providers=["spotify", "apple_music", "youtube_music", "amazon_music"],
    ),
    
    "VIDEO": PrimitiveDefinition(
        name="VIDEO",
        description="Video operations",
        operations=[
            {"name": "search", "params": ["query"], "description": "Search videos"},
            {"name": "get_info", "params": ["video_id"], "description": "Get video info"},
            {"name": "get_transcript", "params": ["video_id"], "description": "Get transcript"},
            {"name": "download", "params": ["video_id", "path", "quality?"], "description": "Download video"},
            {"name": "upload", "params": ["path", "title", "description?"], "description": "Upload video"},
            {"name": "get_playlist", "params": ["playlist_id"], "description": "Get playlist"},
        ],
        providers=["youtube", "vimeo"],
    ),
    
    # ========================================
    #  TRAVEL & TRANSPORTATION
    # ========================================
    
    "RIDE": PrimitiveDefinition(
        name="RIDE",
        description="Ride-sharing operations",
        operations=[
            {"name": "estimate", "params": ["pickup", "dropoff"], "description": "Get fare estimate"},
            {"name": "request", "params": ["pickup", "dropoff", "type?"], "description": "Request ride"},
            {"name": "cancel", "params": ["ride_id"], "description": "Cancel ride"},
            {"name": "track", "params": ["ride_id"], "description": "Track ride"},
            {"name": "history", "params": ["limit?"], "description": "Get ride history"},
        ],
        providers=["uber", "lyft"],
    ),
    
    "TRAVEL": PrimitiveDefinition(
        name="TRAVEL",
        description="Travel booking operations",
        operations=[
            {"name": "search_flights", "params": ["origin", "destination", "date", "return_date?"], "description": "Search flights"},
            {"name": "search_hotels", "params": ["location", "checkin", "checkout", "guests?"], "description": "Search hotels"},
            {"name": "get_booking", "params": ["booking_id"], "description": "Get booking details"},
            {"name": "get_itinerary", "params": ["trip_id?"], "description": "Get trip itinerary"},
            {"name": "checkin", "params": ["booking_id"], "description": "Online check-in"},
        ],
        providers=["google_flights", "expedia", "kayak", "airline_apis"],
    ),
    
    # ========================================
    #  SMART HOME
    # ========================================
    
    "HOME": PrimitiveDefinition(
        name="HOME",
        description="Smart home operations",
        operations=[
            {"name": "list_devices", "params": [], "description": "List devices"},
            {"name": "get_state", "params": ["device_id"], "description": "Get device state"},
            {"name": "set_state", "params": ["device_id", "state"], "description": "Set device state"},
            {"name": "turn_on", "params": ["device_id"], "description": "Turn on device"},
            {"name": "turn_off", "params": ["device_id"], "description": "Turn off device"},
            {"name": "set_temperature", "params": ["device_id", "temperature"], "description": "Set thermostat"},
            {"name": "run_routine", "params": ["routine_name"], "description": "Run routine/scene"},
        ],
        providers=["alexa", "google_home", "homekit", "smartthings", "hue"],
    ),
    
    # ========================================
    #  E-COMMERCE
    # ========================================
    
    "SHOPPING": PrimitiveDefinition(
        name="SHOPPING",
        description="E-commerce operations",
        operations=[
            {"name": "search", "params": ["query", "filters?"], "description": "Search products"},
            {"name": "get_product", "params": ["product_id"], "description": "Get product details"},
            {"name": "add_to_cart", "params": ["product_id", "quantity?"], "description": "Add to cart"},
            {"name": "get_cart", "params": [], "description": "Get cart contents"},
            {"name": "track_order", "params": ["order_id"], "description": "Track order"},
            {"name": "get_orders", "params": ["limit?"], "description": "Get order history"},
            {"name": "reorder", "params": ["order_id"], "description": "Reorder previous"},
            {"name": "price_alert", "params": ["product_id", "target_price"], "description": "Set price alert"},
        ],
        providers=["amazon", "ebay", "walmart", "target"],
    ),
    
    # ========================================
    #  SYSTEM
    # ========================================
    
    "SYSTEM": PrimitiveDefinition(
        name="SYSTEM",
        description="Local system operations",
        operations=[
            {"name": "run", "params": ["command"], "description": "Run shell command"},
            {"name": "open_app", "params": ["app_name"], "description": "Open application"},
            {"name": "close_app", "params": ["app_name"], "description": "Close application"},
            {"name": "get_clipboard", "params": [], "description": "Get clipboard content"},
            {"name": "set_clipboard", "params": ["content"], "description": "Set clipboard"},
            {"name": "notify", "params": ["title", "message"], "description": "Show notification"},
            {"name": "get_info", "params": [], "description": "Get system info"},
            {"name": "screenshot", "params": ["path?"], "description": "Take screenshot"},
        ],
        providers=["windows", "macos", "linux"],
    ),
    
    "BROWSER": PrimitiveDefinition(
        name="BROWSER",
        description="Browser automation",
        operations=[
            {"name": "open", "params": ["url"], "description": "Open URL"},
            {"name": "search", "params": ["query"], "description": "Search Google"},
            {"name": "get_tabs", "params": [], "description": "List open tabs"},
            {"name": "close_tab", "params": ["tab_id?"], "description": "Close tab"},
            {"name": "get_bookmarks", "params": ["folder?"], "description": "Get bookmarks"},
            {"name": "add_bookmark", "params": ["url", "title", "folder?"], "description": "Add bookmark"},
            {"name": "get_history", "params": ["limit?"], "description": "Get browser history"},
        ],
        providers=["chrome", "firefox", "safari", "edge"],
    ),
}


# ============================================================
#  SUMMARY STATISTICS
# ============================================================

def get_primitive_summary() -> Dict[str, Any]:
    """Get summary of all primitives."""
    total_ops = sum(len(p.operations) for p in PRIMITIVES.values())
    total_providers = len(set(
        provider 
        for p in PRIMITIVES.values() 
        for provider in p.providers
    ))
    
    return {
        "total_primitives": len(PRIMITIVES),
        "total_operations": total_ops,
        "total_providers": total_providers,
        "categories": {
            "Communication": ["EMAIL", "CHAT", "MEETING", "SMS"],
            "Calendar & Tasks": ["CALENDAR", "TASKS"],
            "Files & Storage": ["FILE", "CLOUD_STORAGE"],
            "Documents": ["DOCUMENT", "SPREADSHEET", "PRESENTATION", "NOTES"],
            "People": ["CONTACTS"],
            "Data": ["COMPUTE", "KNOWLEDGE"],
            "Web": ["WEB", "BROWSER"],
            "Development": ["CODE_REPO", "PROJECT"],
            "Finance": ["FINANCE"],
            "Social": ["SOCIAL"],
            "Media": ["PHOTO", "MUSIC", "VIDEO"],
            "Travel": ["RIDE", "TRAVEL"],
            "Smart Home": ["HOME"],
            "Shopping": ["SHOPPING"],
            "System": ["SYSTEM"],
        },
        "by_category": {
            cat: sum(len(PRIMITIVES[p].operations) for p in prims if p in PRIMITIVES)
            for cat, prims in {
                "Communication": ["EMAIL", "CHAT", "MEETING", "SMS"],
                "Calendar & Tasks": ["CALENDAR", "TASKS"],
                "Files & Storage": ["FILE", "CLOUD_STORAGE"],
                "Documents": ["DOCUMENT", "SPREADSHEET", "PRESENTATION", "NOTES"],
                "People": ["CONTACTS"],
                "Data": ["COMPUTE", "KNOWLEDGE"],
                "Web": ["WEB", "BROWSER"],
                "Development": ["CODE_REPO", "PROJECT"],
                "Finance": ["FINANCE"],
                "Social": ["SOCIAL"],
                "Media": ["PHOTO", "MUSIC", "VIDEO"],
                "Travel": ["RIDE", "TRAVEL"],
                "Smart Home": ["HOME"],
                "Shopping": ["SHOPPING"],
                "System": ["SYSTEM"],
            }.items()
        },
    }


def get_llm_capabilities_prompt() -> str:
    """Generate a comprehensive prompt for the LLM describing all capabilities."""
    lines = ["# Available Primitives and Operations\n"]
    
    for name, primitive in sorted(PRIMITIVES.items()):
        lines.append(f"\n## {name}")
        lines.append(f"{primitive.description}")
        lines.append(f"Providers: {', '.join(primitive.providers)}")
        lines.append("\nOperations:")
        for op in primitive.operations:
            params = ", ".join(op["params"])
            lines.append(f"  - {name}.{op['name']}({params}): {op['description']}")
    
    return "\n".join(lines)


# Print summary when run directly
if __name__ == "__main__":
    import json
    summary = get_primitive_summary()
    print(f"\n{'='*60}")
    print("APEX UNIVERSAL PRIMITIVES")
    print(f"{'='*60}")
    print(f"\nTotal Primitives: {summary['total_primitives']}")
    print(f"Total Operations: {summary['total_operations']}")
    print(f"Total Providers:  {summary['total_providers']}")
    print(f"\nOperations by Category:")
    for cat, count in summary['by_category'].items():
        print(f"  {cat}: {count}")
    print(f"\n{'='*60}")
