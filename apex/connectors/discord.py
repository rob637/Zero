"""
Discord Connector - Community Messaging Integration

Provides access to Discord servers for messaging, channels, and reactions
via the Discord Bot API.

Uses Discord HTTP API with Bot Token authentication.

Capabilities:
- Channel messaging (send, list, reply)
- Server/guild management (list channels, members)
- Reactions (add, remove)
- Direct messages
- Message search

Setup:
    from connectors.discord import DiscordConnector
    
    discord = DiscordConnector(bot_token="...")
    await discord.connect()
    
    await discord.send_message(channel_id="...", text="Hello!")
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


@dataclass
class DiscordMessage:
    """Discord message."""
    id: str
    content: str
    author: str
    channel_id: str
    timestamp: Optional[str] = None
    reply_to: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict) -> "DiscordMessage":
        author = data.get("author", {}).get("username", "Unknown")
        ref = data.get("message_reference", {})
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            author=author,
            channel_id=data.get("channel_id", ""),
            timestamp=data.get("timestamp"),
            reply_to=ref.get("message_id"),
        )


@dataclass
class DiscordChannel:
    """Discord channel."""
    id: str
    name: str
    guild_id: Optional[str] = None
    type: int = 0  # 0=text, 2=voice, 4=category, etc.

    @classmethod
    def from_api(cls, data: Dict) -> "DiscordChannel":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            guild_id=data.get("guild_id"),
            type=data.get("type", 0),
        )


class DiscordConnector:
    """Discord connector via Bot HTTP API."""

    def __init__(self, bot_token: Optional[str] = None):
        self._token = bot_token or os.environ.get("DISCORD_BOT_TOKEN", "")
        self._http = None

    async def connect(self):
        """Initialize HTTP client."""
        if not self._token:
            raise ValueError("No Discord bot token. Set DISCORD_BOT_TOKEN.")

        import httpx
        self._http = httpx.AsyncClient(
            base_url=DISCORD_API,
            headers={
                "Authorization": f"Bot {self._token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    async def list_guilds(self) -> List[Dict]:
        """List guilds (servers) the bot is in."""
        await self._ensure_client()
        resp = await self._http.get("/users/@me/guilds")
        resp.raise_for_status()
        return resp.json()

    async def list_channels(self, guild_id: str, limit: int = 50) -> List[DiscordChannel]:
        """List channels in a guild."""
        await self._ensure_client()
        resp = await self._http.get(f"/guilds/{guild_id}/channels")
        resp.raise_for_status()
        channels = [DiscordChannel.from_api(c) for c in resp.json()]
        # Filter to text channels only
        return [c for c in channels if c.type == 0][:limit]

    async def list_messages(self, channel_id: str, limit: int = 20) -> List[DiscordMessage]:
        """List recent messages in a channel."""
        await self._ensure_client()
        resp = await self._http.get(
            f"/channels/{channel_id}/messages",
            params={"limit": min(limit, 100)},
        )
        resp.raise_for_status()
        return [DiscordMessage.from_api(m) for m in resp.json()]

    async def send_message(self, channel_id: str, text: str) -> DiscordMessage:
        """Send a message to a channel."""
        await self._ensure_client()
        resp = await self._http.post(
            f"/channels/{channel_id}/messages",
            json={"content": text},
        )
        resp.raise_for_status()
        return DiscordMessage.from_api(resp.json())

    async def reply_to_message(
        self, channel_id: str, message_id: str, text: str
    ) -> DiscordMessage:
        """Reply to a specific message."""
        await self._ensure_client()
        resp = await self._http.post(
            f"/channels/{channel_id}/messages",
            json={
                "content": text,
                "message_reference": {"message_id": message_id},
            },
        )
        resp.raise_for_status()
        return DiscordMessage.from_api(resp.json())

    async def add_reaction(self, channel_id: str, message_id: str, emoji: str):
        """Add a reaction to a message. Emoji is URL-encoded unicode or custom emoji name:id."""
        await self._ensure_client()
        resp = await self._http.put(
            f"/channels/{channel_id}/messages/{message_id}/reactions/{emoji}/@me",
        )
        resp.raise_for_status()

    async def send_dm(self, user_id: str, text: str) -> DiscordMessage:
        """Send a direct message to a user."""
        await self._ensure_client()
        # Create DM channel first
        resp = await self._http.post(
            "/users/@me/channels",
            json={"recipient_id": user_id},
        )
        resp.raise_for_status()
        dm_channel_id = resp.json()["id"]

        return await self.send_message(dm_channel_id, text)

    async def search_messages(self, guild_id: str, query: str, limit: int = 20) -> List[Dict]:
        """Search messages in a guild."""
        await self._ensure_client()
        resp = await self._http.get(
            f"/guilds/{guild_id}/messages/search",
            params={"content": query, "limit": min(limit, 25)},
        )
        resp.raise_for_status()
        messages = resp.json().get("messages", [])
        # Discord returns messages as arrays of arrays
        return [DiscordMessage.from_api(m[0]) for m in messages if m]

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
