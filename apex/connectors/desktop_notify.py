"""
Desktop Notifications Connector

Provides native desktop notifications and alerts via OS-level
notification systems (Windows toast, macOS Notification Center, Linux notify-send).

Capabilities:
- Show desktop notifications
- Play alert sounds
- System tray balloon tips

Setup:
    from connectors.desktop_notify import DesktopNotifyConnector
    
    notify = DesktopNotifyConnector()
    await notify.send(title="Reminder", message="Meeting in 5 minutes")
"""

import asyncio
import logging
import platform
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


class DesktopNotifyConnector:
    """Cross-platform desktop notifications."""

    def __init__(self):
        self._system = platform.system().lower()
        self.connected = True

    async def connect(self) -> bool:
        """Desktop notifications are always available."""
        self.connected = True
        return True

    async def send(
        self,
        title: str = "Telic",
        message: str = "",
        urgency: str = "normal",
    ) -> dict:
        """Send a desktop notification.
        
        Args:
            title: Notification title
            message: Notification body text
            urgency: low, normal, or high (maps to OS urgency levels)
        """
        try:
            if self._system == "windows":
                return await self._windows_notify(title, message, urgency)
            elif self._system == "darwin":
                return await self._macos_notify(title, message)
            elif self._system == "linux":
                return await self._linux_notify(title, message, urgency)
            else:
                return {"sent": False, "error": f"Unsupported platform: {self._system}"}
        except Exception as e:
            return {"sent": False, "error": str(e)}

    async def _windows_notify(self, title: str, message: str, urgency: str) -> dict:
        """Windows toast notification via PowerShell."""
        # Escape quotes for PowerShell
        safe_title = title.replace("'", "''").replace('"', '`"')
        safe_message = message.replace("'", "''").replace('"', '`"')
        
        script = f"""
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
        $xml = @"
        <toast>
            <visual>
                <binding template="ToastGeneric">
                    <text>{safe_title}</text>
                    <text>{safe_message}</text>
                </binding>
            </visual>
        </toast>
"@
        $XmlDocument = [Windows.Data.Xml.Dom.XmlDocument]::new()
        $XmlDocument.LoadXml($xml)
        $AppId = 'Telic'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show(
            [Windows.UI.Notifications.ToastNotification]::new($XmlDocument)
        )
        """
        
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-Command", script,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return {"sent": True, "platform": "windows"}

    async def _macos_notify(self, title: str, message: str) -> dict:
        """macOS notification via osascript."""
        safe_title = title.replace('"', '\\"')
        safe_message = message.replace('"', '\\"')
        
        script = f'display notification "{safe_message}" with title "{safe_title}"'
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return {"sent": True, "platform": "macos"}

    async def _linux_notify(self, title: str, message: str, urgency: str) -> dict:
        """Linux notification via notify-send."""
        urgency_map = {"low": "low", "normal": "normal", "high": "critical"}
        level = urgency_map.get(urgency, "normal")
        
        proc = await asyncio.create_subprocess_exec(
            "notify-send", "-u", level, title, message,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=10)
        return {"sent": True, "platform": "linux"}
