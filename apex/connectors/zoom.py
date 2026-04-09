"""
Zoom Connector - Zoom Meetings & Webinars

Meetings, users, recordings, and webinars via Zoom REST API v2.

Setup:
    1. Go to https://marketplace.zoom.us → Build App → Server-to-Server OAuth or OAuth
    2. For personal use: Settings > Developer > Personal Access Token
    
    export ZOOM_ACCOUNT_ID="your-account-id"
    export ZOOM_CLIENT_ID="your-client-id"
    export ZOOM_CLIENT_SECRET="your-client-secret"

    Or for simpler setup with a personal access token:
    export ZOOM_API_KEY="your-personal-access-token"

    from connectors.zoom import ZoomConnector
    zoom = ZoomConnector()
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.zoom.us/v2"
OAUTH_URL = "https://zoom.us/oauth/token"


class ZoomConnector:
    """Zoom meetings, users, and recordings via REST API."""

    def __init__(
        self,
        account_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.account_id = account_id or os.environ.get("ZOOM_ACCOUNT_ID", "")
        self.client_id = client_id or os.environ.get("ZOOM_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("ZOOM_CLIENT_SECRET", "")
        self.api_key = api_key or os.environ.get("ZOOM_API_KEY", "")
        self._access_token = ""
        self._token_expires = 0
        self.connected = bool(self.api_key) or bool(self.account_id and self.client_id and self.client_secret)

    async def connect(self) -> bool:
        """Validate Zoom API credentials."""
        self.connected = bool(self.api_key) or bool(self.account_id and self.client_id and self.client_secret)
        return self.connected

    async def _get_token(self) -> str:
        """Get or refresh OAuth access token."""
        if self.api_key:
            return self.api_key
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                OAUTH_URL,
                params={"grant_type": "account_credentials", "account_id": self.account_id},
                auth=(self.client_id, self.client_secret),
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 3600) - 60
            return self._access_token

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        import httpx
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params or {},
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, data: Optional[Dict] = None) -> Any:
        import httpx
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=data or {},
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def _patch(self, path: str, data: Optional[Dict] = None) -> bool:
        import httpx
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=data or {},
            )
            resp.raise_for_status()
            return True

    async def _delete(self, path: str) -> bool:
        import httpx
        token = await self._get_token()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(
                f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return True

    # ── User ──

    async def me(self) -> Dict:
        """Get the current authenticated user's profile."""
        data = await self._get("/users/me")
        return {
            "id": data.get("id", ""),
            "email": data.get("email", ""),
            "first_name": data.get("first_name", ""),
            "last_name": data.get("last_name", ""),
            "display_name": f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(),
            "type": data.get("type"),
            "timezone": data.get("timezone", ""),
            "pmi": data.get("pmi"),
        }

    # ── Meetings ──

    async def list_meetings(
        self,
        type: str = "scheduled",
        page_size: int = 30,
    ) -> List[Dict]:
        """List meetings for the current user.
        
        Args:
            type: 'scheduled', 'live', 'upcoming', 'upcoming_meetings', 'previous_meetings'
            page_size: Results per page (max 300, default 30)
        """
        data = await self._get("/users/me/meetings", {
            "type": type,
            "page_size": min(page_size, 300),
        })
        return [self._parse_meeting(m) for m in data.get("meetings", [])]

    async def get_meeting(self, meeting_id: str) -> Dict:
        """Get meeting details.
        
        Args:
            meeting_id: Meeting ID or UUID
        """
        data = await self._get(f"/meetings/{meeting_id}")
        result = self._parse_meeting(data)
        result["agenda"] = data.get("agenda", "")
        result["join_url"] = data.get("join_url", "")
        result["password"] = data.get("password", "")
        if data.get("settings"):
            s = data["settings"]
            result["settings"] = {
                "host_video": s.get("host_video", True),
                "participant_video": s.get("participant_video", True),
                "mute_upon_entry": s.get("mute_upon_entry", False),
                "waiting_room": s.get("waiting_room", False),
                "auto_recording": s.get("auto_recording", "none"),
            }
        return result

    async def create_meeting(
        self,
        topic: str,
        start_time: Optional[str] = None,
        duration: int = 60,
        timezone: Optional[str] = None,
        agenda: Optional[str] = None,
        password: Optional[str] = None,
        waiting_room: bool = False,
        meeting_type: int = 2,
    ) -> Dict:
        """Create a meeting.
        
        Args:
            topic: Meeting title
            start_time: Start time (ISO 8601, e.g. "2026-04-15T10:00:00Z")
            duration: Duration in minutes (default 60)
            timezone: Timezone (e.g. "America/New_York")
            agenda: Meeting description/agenda
            password: Meeting password (auto-generated if not provided)
            waiting_room: Enable waiting room
            meeting_type: 1=instant, 2=scheduled, 3=recurring no fixed time, 8=recurring fixed time
        """
        body: Dict[str, Any] = {
            "topic": topic,
            "type": meeting_type,
            "duration": duration,
            "settings": {
                "waiting_room": waiting_room,
            },
        }
        if start_time:
            body["start_time"] = start_time
        if timezone:
            body["timezone"] = timezone
        if agenda:
            body["agenda"] = agenda
        if password:
            body["password"] = password

        data = await self._post("/users/me/meetings", body)
        result = self._parse_meeting(data)
        result["join_url"] = data.get("join_url", "")
        result["start_url"] = data.get("start_url", "")
        result["password"] = data.get("password", "")
        return result

    async def update_meeting(
        self,
        meeting_id: str,
        topic: Optional[str] = None,
        start_time: Optional[str] = None,
        duration: Optional[int] = None,
        agenda: Optional[str] = None,
    ) -> bool:
        """Update a meeting.
        
        Args:
            meeting_id: Meeting ID
            topic: New topic
            start_time: New start time (ISO 8601)
            duration: New duration in minutes
            agenda: New agenda
        """
        body: Dict[str, Any] = {}
        if topic:
            body["topic"] = topic
        if start_time:
            body["start_time"] = start_time
        if duration:
            body["duration"] = duration
        if agenda:
            body["agenda"] = agenda
        return await self._patch(f"/meetings/{meeting_id}", body)

    async def delete_meeting(self, meeting_id: str) -> bool:
        """Delete a meeting.
        
        Args:
            meeting_id: Meeting ID
        """
        return await self._delete(f"/meetings/{meeting_id}")

    # ── Participants ──

    async def get_meeting_participants(self, meeting_id: str) -> List[Dict]:
        """Get participants from a past meeting.
        
        Args:
            meeting_id: Meeting UUID (from past meetings)
        """
        data = await self._get(f"/past_meetings/{meeting_id}/participants", {"page_size": 300})
        return [{
            "name": p.get("name", ""),
            "email": p.get("user_email", ""),
            "join_time": p.get("join_time", ""),
            "leave_time": p.get("leave_time", ""),
            "duration": p.get("duration"),
        } for p in data.get("participants", [])]

    # ── Recordings ──

    async def list_recordings(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> List[Dict]:
        """List cloud recordings.
        
        Args:
            from_date: Start date (YYYY-MM-DD, default: last 30 days)
            to_date: End date (YYYY-MM-DD)
        """
        params: Dict[str, str] = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        data = await self._get("/users/me/recordings", params)
        recordings = []
        for m in data.get("meetings", []):
            files = [{
                "type": f.get("recording_type", ""),
                "size_mb": round(f.get("file_size", 0) / 1048576, 1),
                "download_url": f.get("download_url", ""),
                "play_url": f.get("play_url", ""),
                "status": f.get("status", ""),
            } for f in m.get("recording_files", [])]
            recordings.append({
                "meeting_id": m.get("id"),
                "topic": m.get("topic", ""),
                "start_time": m.get("start_time", ""),
                "duration": m.get("duration"),
                "total_size_mb": round(m.get("total_size", 0) / 1048576, 1),
                "file_count": len(files),
                "files": files,
            })
        return recordings

    # ── Helpers ──

    def _parse_meeting(self, m: Dict) -> Dict:
        """Parse a meeting into a clean dict."""
        result: Dict[str, Any] = {
            "id": m.get("id"),
            "topic": m.get("topic", ""),
            "type": m.get("type"),
        }
        if m.get("start_time"):
            result["start_time"] = m["start_time"]
        if m.get("duration"):
            result["duration"] = m["duration"]
        if m.get("timezone"):
            result["timezone"] = m["timezone"]
        if m.get("status"):
            result["status"] = m["status"]
        if m.get("created_at"):
            result["created_at"] = m["created_at"]
        if m.get("start_url"):
            result["start_url"] = m["start_url"]
        if m.get("join_url"):
            result["join_url"] = m["join_url"]
        return result
