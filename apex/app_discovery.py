"""
App Discovery

Scans the local system for installed applications and maps them to
available connectors. Used during onboarding to suggest connections.

Key principle: Discovery is a BOOST signal, not a gate.
  - "Found Slack" → promote Slack connector in setup UI
  - "Didn't find Slack" → still available (user may use web version)

Supports Windows, macOS, and Linux. Each platform has different
scan strategies:
  - Windows: Start Menu shortcuts, registry (HKLM/HKCU Uninstall keys)
  - macOS: /Applications folder
  - Linux: .desktop files in /usr/share/applications
"""

import os
import platform
import glob
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DiscoveredApp:
    """An application found on the local system."""
    name: str                    # Display name (e.g., "Slack")
    app_id: str                  # Normalized identifier (e.g., "slack")
    path: Optional[str] = None   # Install path if known
    version: Optional[str] = None
    source: str = ""             # How we found it: "startmenu", "registry", "applications", etc.


@dataclass
class ConnectorSuggestion:
    """A suggested connector based on discovered apps."""
    connector_name: str          # Registry connector name (e.g., "slack")
    display_name: str            # Human-readable (e.g., "Slack")
    reason: str                  # Why we're suggesting (e.g., "Slack is installed on your PC")
    priority: int = 0            # Higher = more prominent in UI
    detected_app: Optional[str] = None  # The app that triggered this


@dataclass
class DiscoveryResult:
    """Full result of an app discovery scan."""
    apps: List[DiscoveredApp] = field(default_factory=list)
    suggestions: List[ConnectorSuggestion] = field(default_factory=list)
    platform: str = ""
    scan_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# App → Connector mapping
#
# Maps normalized app names to connector suggestions.
# Multiple app names can map to the same connector (e.g., "outlook" and
# "microsoft outlook" both → outlook connector).
# ---------------------------------------------------------------------------

_APP_TO_CONNECTOR: Dict[str, Dict] = {
    # Communication
    "slack": {
        "connector": "slack",
        "display": "Slack",
        "priority": 90,
    },
    "discord": {
        "connector": "discord",
        "display": "Discord",
        "priority": 70,
    },
    "telegram": {
        "connector": "telegram",
        "display": "Telegram",
        "priority": 60,
    },
    "microsoft teams": {
        "connector": "teams",
        "display": "Microsoft Teams",
        "priority": 85,
    },
    "teams": {
        "connector": "teams",
        "display": "Microsoft Teams",
        "priority": 85,
    },
    "zoom": {
        "connector": "zoom",
        "display": "Zoom",
        "priority": 75,
    },

    # Email & calendar
    "outlook": {
        "connector": "outlook",
        "display": "Microsoft Outlook",
        "priority": 95,
        "also": ["outlook_calendar", "microsoft_contacts", "microsoft_todo"],
    },
    "microsoft outlook": {
        "connector": "outlook",
        "display": "Microsoft Outlook",
        "priority": 95,
        "also": ["outlook_calendar", "microsoft_contacts", "microsoft_todo"],
    },
    "thunderbird": {
        "connector": None,  # No connector yet, but worth noting
        "display": "Thunderbird",
        "priority": 20,
    },

    # Productivity
    "notion": {
        "connector": "notion",
        "display": "Notion",
        "priority": 80,
    },
    "todoist": {
        "connector": "todoist",
        "display": "Todoist",
        "priority": 70,
    },
    "trello": {
        "connector": "trello",
        "display": "Trello",
        "priority": 65,
    },

    # Cloud storage
    "dropbox": {
        "connector": "dropbox",
        "display": "Dropbox",
        "priority": 75,
    },
    "google drive": {
        "connector": "drive",
        "display": "Google Drive",
        "priority": 80,
    },
    "onedrive": {
        "connector": "onedrive",
        "display": "OneDrive",
        "priority": 80,
    },
    "microsoft onedrive": {
        "connector": "onedrive",
        "display": "OneDrive",
        "priority": 80,
    },

    # Dev tools
    "visual studio code": {
        "connector": "github",
        "display": "GitHub (VS Code detected)",
        "priority": 60,
    },
    "vs code": {
        "connector": "github",
        "display": "GitHub (VS Code detected)",
        "priority": 60,
    },
    "github desktop": {
        "connector": "github",
        "display": "GitHub",
        "priority": 80,
    },

    # Media
    "spotify": {
        "connector": "spotify",
        "display": "Spotify",
        "priority": 70,
    },

    # Finance
    "stripe": {
        "connector": "stripe",
        "display": "Stripe",
        "priority": 50,
    },

    # Smart home
    "smartthings": {
        "connector": "smartthings",
        "display": "SmartThings",
        "priority": 50,
    },

    # Browsers (indicate web-based usage patterns)
    "google chrome": {
        "connector": None,
        "display": "Google Chrome",
        "priority": 0,
        "hint_connectors": ["gmail", "calendar", "drive", "google_sheets"],
    },
    "chrome": {
        "connector": None,
        "display": "Google Chrome",
        "priority": 0,
        "hint_connectors": ["gmail", "calendar", "drive", "google_sheets"],
    },
    "microsoft edge": {
        "connector": None,
        "display": "Microsoft Edge",
        "priority": 0,
        "hint_connectors": ["outlook", "outlook_calendar", "onedrive", "microsoft_todo"],
    },
}


# ---------------------------------------------------------------------------
# Platform scanners
# ---------------------------------------------------------------------------

def _scan_windows() -> List[DiscoveredApp]:
    """Scan Windows for installed applications."""
    apps: Dict[str, DiscoveredApp] = {}  # Dedupe by app_id

    # Strategy 1: Start Menu shortcuts (.lnk files)
    start_menu_paths = [
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
    ]
    for base in start_menu_paths:
        if not os.path.isdir(base):
            continue
        for lnk in glob.glob(os.path.join(base, "**", "*.lnk"), recursive=True):
            name = Path(lnk).stem
            # Skip uninstallers and system utilities
            lower = name.lower()
            if any(skip in lower for skip in ["uninstall", "readme", "help", "license", "changelog"]):
                continue
            app_id = _normalize_app_name(name)
            if app_id and app_id not in apps:
                apps[app_id] = DiscoveredApp(
                    name=name, app_id=app_id, path=lnk, source="startmenu"
                )

    # Strategy 2: Registry uninstall keys
    try:
        import winreg
        keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, key_path in keys:
            try:
                key = winreg.OpenKey(hive, key_path)
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey = winreg.OpenKey(key, subkey_name)
                        try:
                            name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                            app_id = _normalize_app_name(name)
                            if app_id and app_id not in apps:
                                version = None
                                try:
                                    version, _ = winreg.QueryValueEx(subkey, "DisplayVersion")
                                except (FileNotFoundError, OSError):
                                    pass
                                install_path = None
                                try:
                                    install_path, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                except (FileNotFoundError, OSError):
                                    pass
                                apps[app_id] = DiscoveredApp(
                                    name=name, app_id=app_id,
                                    path=install_path, version=version,
                                    source="registry",
                                )
                        except (FileNotFoundError, OSError):
                            pass
                        finally:
                            winreg.CloseKey(subkey)
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)
            except OSError:
                continue
    except ImportError:
        pass  # Not on Windows

    # Strategy 3: UWP / Microsoft Store apps (AppxPackage names)
    appx_path = os.path.expandvars(r"%ProgramFiles%\WindowsApps")
    if os.path.isdir(appx_path):
        try:
            for entry in os.listdir(appx_path):
                lower = entry.lower()
                # Match known UWP app package prefixes
                uwp_map = {
                    "slack": "slack",
                    "spotify": "spotify",
                    "discord": "discord",
                    "microsoft.todos": "microsoft_todo",  # MS To Do
                    "microsoft.office.outlook": "outlook",
                    "microsoft.teams": "teams",
                }
                for pkg_prefix, app_id in uwp_map.items():
                    if pkg_prefix in lower and app_id not in apps:
                        apps[app_id] = DiscoveredApp(
                            name=app_id.title(), app_id=app_id,
                            path=os.path.join(appx_path, entry),
                            source="uwp",
                        )
        except PermissionError:
            pass  # WindowsApps is often restricted

    return list(apps.values())


def _scan_macos() -> List[DiscoveredApp]:
    """Scan macOS for installed applications."""
    apps: Dict[str, DiscoveredApp] = {}

    app_dirs = ["/Applications", os.path.expanduser("~/Applications")]
    for app_dir in app_dirs:
        if not os.path.isdir(app_dir):
            continue
        for entry in os.listdir(app_dir):
            if entry.endswith(".app"):
                name = entry[:-4]  # Strip .app
                app_id = _normalize_app_name(name)
                if app_id and app_id not in apps:
                    apps[app_id] = DiscoveredApp(
                        name=name, app_id=app_id,
                        path=os.path.join(app_dir, entry),
                        source="applications",
                    )

    # Also check Homebrew casks
    brew_cask_dir = "/opt/homebrew/Caskroom"
    if not os.path.isdir(brew_cask_dir):
        brew_cask_dir = "/usr/local/Caskroom"
    if os.path.isdir(brew_cask_dir):
        for entry in os.listdir(brew_cask_dir):
            app_id = _normalize_app_name(entry)
            if app_id and app_id not in apps:
                apps[app_id] = DiscoveredApp(
                    name=entry, app_id=app_id,
                    path=os.path.join(brew_cask_dir, entry),
                    source="homebrew",
                )

    return list(apps.values())


def _scan_linux() -> List[DiscoveredApp]:
    """Scan Linux for installed applications."""
    apps: Dict[str, DiscoveredApp] = {}

    # .desktop files
    desktop_dirs = [
        "/usr/share/applications",
        "/usr/local/share/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/snap/applications",
    ]

    for desktop_dir in desktop_dirs:
        if not os.path.isdir(desktop_dir):
            continue
        for f in glob.glob(os.path.join(desktop_dir, "*.desktop")):
            try:
                name = None
                with open(f, "r", errors="ignore") as fh:
                    for line in fh:
                        if line.startswith("Name="):
                            name = line.split("=", 1)[1].strip()
                            break
                if name:
                    app_id = _normalize_app_name(name)
                    if app_id and app_id not in apps:
                        apps[app_id] = DiscoveredApp(
                            name=name, app_id=app_id, path=f,
                            source="desktop_file",
                        )
            except (OSError, UnicodeDecodeError):
                continue

    return list(apps.values())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_app_name(name: str) -> str:
    """Normalize an app name to a lowercase identifier for matching."""
    if not name:
        return ""
    # Keep only alphanumeric and spaces, lowercase
    cleaned = "".join(c if c.isalnum() or c == " " else " " for c in name)
    cleaned = " ".join(cleaned.lower().split())  # Collapse whitespace
    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_apps() -> DiscoveryResult:
    """Scan the local system for installed applications.

    Returns a DiscoveryResult with discovered apps and connector suggestions.
    Safe to call on any platform — returns empty results if scanning fails.
    """
    import time
    start = time.monotonic()

    system = platform.system()
    apps: List[DiscoveredApp] = []

    try:
        if system == "Windows":
            apps = _scan_windows()
        elif system == "Darwin":
            apps = _scan_macos()
        elif system == "Linux":
            apps = _scan_linux()
        else:
            logger.warning(f"Unknown platform: {system}")
    except Exception as e:
        logger.error(f"App scan failed: {e}")

    # Generate connector suggestions from discovered apps
    suggestions = _generate_suggestions(apps)

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(f"App discovery: found {len(apps)} apps, {len(suggestions)} suggestions in {elapsed_ms:.0f}ms")

    return DiscoveryResult(
        apps=apps,
        suggestions=suggestions,
        platform=system,
        scan_time_ms=elapsed_ms,
    )


def _generate_suggestions(apps: List[DiscoveredApp]) -> List[ConnectorSuggestion]:
    """Map discovered apps to connector suggestions."""
    suggestions: Dict[str, ConnectorSuggestion] = {}  # Dedupe by connector name
    hint_connectors: Set[str] = set()

    for app in apps:
        app_id = app.app_id

        # Check direct match
        mapping = _APP_TO_CONNECTOR.get(app_id)
        if not mapping:
            # Try partial matching for common names
            for known_name, m in _APP_TO_CONNECTOR.items():
                if known_name in app_id or app_id in known_name:
                    mapping = m
                    break

        if not mapping:
            continue

        connector = mapping.get("connector")
        if connector and connector not in suggestions:
            suggestions[connector] = ConnectorSuggestion(
                connector_name=connector,
                display_name=mapping["display"],
                reason=f"{app.name} is installed on your computer",
                priority=mapping.get("priority", 50),
                detected_app=app.name,
            )

        # Handle "also" connectors (e.g., Outlook → also suggest calendar, contacts)
        for also in mapping.get("also", []):
            if also not in suggestions:
                suggestions[also] = ConnectorSuggestion(
                    connector_name=also,
                    display_name=also.replace("_", " ").title(),
                    reason=f"Works with {mapping['display']}",
                    priority=mapping.get("priority", 50) - 5,
                    detected_app=app.name,
                )

        # Collect hint connectors (from browsers etc.)
        for hint in mapping.get("hint_connectors", []):
            hint_connectors.add(hint)

    # Add hint connector suggestions at lower priority (only if not already suggested)
    for hint_connector in hint_connectors:
        if hint_connector not in suggestions:
            suggestions[hint_connector] = ConnectorSuggestion(
                connector_name=hint_connector,
                display_name=hint_connector.replace("_", " ").title(),
                reason="You may use this service in your browser",
                priority=30,
            )

    # Sort by priority descending
    result = sorted(suggestions.values(), key=lambda s: -s.priority)
    return result


def get_all_available_connectors() -> List[Dict]:
    """Get ALL available connectors with discovery boost info.

    Returns every connector we support, with a 'detected' flag
    for ones found on the local system. This ensures web-only
    users still see all options.
    """
    result = scan_apps()

    # Set of connectors we detected
    detected = {s.connector_name for s in result.suggestions}

    # Full list of all connectors we support
    all_connectors = [
        {"name": "gmail", "display": "Gmail", "category": "email", "provider": "google"},
        {"name": "outlook", "display": "Outlook", "category": "email", "provider": "microsoft"},
        {"name": "calendar", "display": "Google Calendar", "category": "calendar", "provider": "google"},
        {"name": "outlook_calendar", "display": "Outlook Calendar", "category": "calendar", "provider": "microsoft"},
        {"name": "contacts", "display": "Google Contacts", "category": "contacts", "provider": "google"},
        {"name": "microsoft_contacts", "display": "Microsoft Contacts", "category": "contacts", "provider": "microsoft"},
        {"name": "drive", "display": "Google Drive", "category": "files", "provider": "google"},
        {"name": "onedrive", "display": "OneDrive", "category": "files", "provider": "microsoft"},
        {"name": "dropbox", "display": "Dropbox", "category": "files", "provider": "dropbox"},
        {"name": "google_sheets", "display": "Google Sheets", "category": "productivity", "provider": "google"},
        {"name": "google_slides", "display": "Google Slides", "category": "productivity", "provider": "google"},
        {"name": "microsoft_excel", "display": "Microsoft Excel", "category": "productivity", "provider": "microsoft"},
        {"name": "microsoft_powerpoint", "display": "PowerPoint", "category": "productivity", "provider": "microsoft"},
        {"name": "microsoft_todo", "display": "Microsoft To Do", "category": "tasks", "provider": "microsoft"},
        {"name": "todoist", "display": "Todoist", "category": "tasks", "provider": "todoist"},
        {"name": "notion", "display": "Notion", "category": "productivity", "provider": "notion"},
        {"name": "trello", "display": "Trello", "category": "productivity", "provider": "trello"},
        {"name": "linear", "display": "Linear", "category": "productivity", "provider": "linear"},
        {"name": "slack", "display": "Slack", "category": "messaging", "provider": "slack"},
        {"name": "discord", "display": "Discord", "category": "messaging", "provider": "discord"},
        {"name": "teams", "display": "Microsoft Teams", "category": "messaging", "provider": "microsoft"},
        {"name": "telegram", "display": "Telegram", "category": "messaging", "provider": "telegram"},
        {"name": "github", "display": "GitHub", "category": "dev", "provider": "github"},
        {"name": "jira", "display": "Jira", "category": "dev", "provider": "atlassian"},
        {"name": "spotify", "display": "Spotify", "category": "media", "provider": "spotify"},
        {"name": "youtube", "display": "YouTube", "category": "media", "provider": "google"},
        {"name": "google_photos", "display": "Google Photos", "category": "media", "provider": "google"},
        {"name": "zoom", "display": "Zoom", "category": "meetings", "provider": "zoom"},
        {"name": "stripe", "display": "Stripe", "category": "finance", "provider": "stripe"},
        {"name": "hubspot", "display": "HubSpot", "category": "crm", "provider": "hubspot"},
        {"name": "smartthings", "display": "SmartThings", "category": "home", "provider": "samsung"},
        {"name": "reddit", "display": "Reddit", "category": "social", "provider": "reddit"},
        {"name": "twitter", "display": "Twitter/X", "category": "social", "provider": "twitter"},
        {"name": "linkedin", "display": "LinkedIn", "category": "social", "provider": "linkedin"},
        {"name": "twilio_sms", "display": "Twilio SMS", "category": "messaging", "provider": "twilio"},
        {"name": "airtable", "display": "Airtable", "category": "productivity", "provider": "airtable"},
        {"name": "onenote", "display": "OneNote", "category": "notes", "provider": "microsoft"},
        {"name": "weather", "display": "Weather", "category": "info", "provider": "openweather"},
        {"name": "news", "display": "News", "category": "info", "provider": "newsapi"},
        {"name": "web_search", "display": "Web Search", "category": "info", "provider": "tavily"},
    ]

    # Enrich with detection info
    for conn in all_connectors:
        conn["detected"] = conn["name"] in detected
        # Find the suggestion if detected
        for s in result.suggestions:
            if s.connector_name == conn["name"]:
                conn["detected_reason"] = s.reason
                conn["detected_app"] = s.detected_app
                conn["boost_priority"] = s.priority
                break

    # Sort: detected first (by priority), then alphabetical
    all_connectors.sort(key=lambda c: (-c.get("boost_priority", 0) if c["detected"] else 0, c["display"]))

    return all_connectors
