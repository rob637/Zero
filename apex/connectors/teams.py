"""
Microsoft Teams Connector - Team Messaging Integration

Provides access to Microsoft Teams for messaging, channels,
and collaboration via Microsoft Graph API.

Uses Microsoft Graph API with OAuth token authentication.

Capabilities:
- Channel messaging (send, list, reply)
- Chat (1:1 and group)
- Channel management (list, create)
- User presence and status
- File sharing in channels

Setup:
    from connectors.teams import TeamsConnector
    
    teams = TeamsConnector()
    await teams.connect()
    
    await teams.send_message(channel_id="...", text="Hello team!")
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class TeamsMessage:
    """Teams message."""
    id: str
    text: str
    sender: str
    channel_id: Optional[str] = None
    chat_id: Optional[str] = None
    timestamp: Optional[str] = None
    reply_to: Optional[str] = None
    attachments: List[Dict] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: Dict) -> "TeamsMessage":
        sender = data.get("from", {}).get("user", {}).get("displayName", "Unknown")
        body = data.get("body", {})
        return cls(
            id=data.get("id", ""),
            text=body.get("content", ""),
            sender=sender,
            channel_id=data.get("channelIdentity", {}).get("channelId"),
            timestamp=data.get("createdDateTime"),
            attachments=data.get("attachments", []),
        )


@dataclass
class TeamsChannel:
    """Teams channel."""
    id: str
    name: str
    team_id: str
    description: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict, team_id: str = "") -> "TeamsChannel":
        return cls(
            id=data.get("id", ""),
            name=data.get("displayName", ""),
            team_id=team_id,
            description=data.get("description"),
        )


class TeamsConnector:
    """Microsoft Teams connector via Graph API."""

    GRAPH_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, token: Optional[str] = None):
        self._token = token or os.environ.get("MS_GRAPH_TOKEN", "")
        self._http = None

    async def connect(self):
        """Initialize HTTP client. Tries MicrosoftAuth if no token."""
        if not self._token:
            try:
                from .microsoft_auth import MicrosoftAuth
                auth = MicrosoftAuth()
                token_data = await asyncio.to_thread(auth.get_token)
                if token_data:
                    self._token = token_data.get("access_token", "")
            except Exception as e:
                logger.warning(f"Microsoft auth failed: {e}")

        if not self._token:
            raise ValueError("No Microsoft Graph token. Set MS_GRAPH_TOKEN or configure Microsoft auth.")

        import httpx
        self._http = httpx.AsyncClient(
            base_url=self.GRAPH_BASE,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    async def list_teams(self) -> List[Dict]:
        """List teams the user belongs to."""
        await self._ensure_client()
        resp = await self._http.get("/me/joinedTeams")
        resp.raise_for_status()
        return resp.json().get("value", [])

    async def list_channels(self, team_id: str, limit: int = 50) -> List[TeamsChannel]:
        """List channels in a team."""
        await self._ensure_client()
        resp = await self._http.get(f"/teams/{team_id}/channels")
        resp.raise_for_status()
        return [TeamsChannel.from_api(c, team_id) for c in resp.json().get("value", [])][:limit]

    async def list_messages(
        self, team_id: str, channel_id: str, limit: int = 20
    ) -> List[TeamsMessage]:
        """List recent messages in a channel."""
        await self._ensure_client()
        resp = await self._http.get(
            f"/teams/{team_id}/channels/{channel_id}/messages",
            params={"$top": limit},
        )
        resp.raise_for_status()
        return [TeamsMessage.from_api(m) for m in resp.json().get("value", [])]

    async def send_message(
        self, team_id: str, channel_id: str, text: str, content_type: str = "text"
    ) -> TeamsMessage:
        """Send a message to a channel."""
        await self._ensure_client()
        resp = await self._http.post(
            f"/teams/{team_id}/channels/{channel_id}/messages",
            json={"body": {"contentType": content_type, "content": text}},
        )
        resp.raise_for_status()
        return TeamsMessage.from_api(resp.json())

    async def reply_to_message(
        self, team_id: str, channel_id: str, message_id: str, text: str
    ) -> TeamsMessage:
        """Reply to a message in a channel thread."""
        await self._ensure_client()
        resp = await self._http.post(
            f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies",
            json={"body": {"contentType": "text", "content": text}},
        )
        resp.raise_for_status()
        return TeamsMessage.from_api(resp.json())

    async def send_chat_message(self, chat_id: str, text: str) -> TeamsMessage:
        """Send a 1:1 or group chat message."""
        await self._ensure_client()
        resp = await self._http.post(
            f"/chats/{chat_id}/messages",
            json={"body": {"contentType": "text", "content": text}},
        )
        resp.raise_for_status()
        return TeamsMessage.from_api(resp.json())

    async def list_chats(self, limit: int = 20) -> List[Dict]:
        """List recent chats."""
        await self._ensure_client()
        resp = await self._http.get("/me/chats", params={"$top": limit})
        resp.raise_for_status()
        return resp.json().get("value", [])

    async def search_messages(self, query: str, limit: int = 20) -> List[Dict]:
        """Search messages across teams."""
        await self._ensure_client()
        resp = await self._http.post(
            "/search/query",
            json={
                "requests": [{
                    "entityTypes": ["chatMessage"],
                    "query": {"queryString": query},
                    "from": 0,
                    "size": limit,
                }]
            },
        )
        resp.raise_for_status()
        hits = resp.json().get("value", [{}])[0].get("hitsContainers", [{}])[0].get("hits", [])
        return [h.get("resource", {}) for h in hits]

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
