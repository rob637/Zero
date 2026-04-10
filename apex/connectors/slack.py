"""
Slack Connector - Workplace Communication Integration

Provides access to Slack workspaces for messaging, channels,
and notifications for proactive workplace awareness.

Uses Slack Web API with OAuth Bot Token.

Capabilities:
- Channel management (list, join, archive)
- Messaging (send, search, react)
- Direct messages
- User/member info
- File sharing
- Status and presence

This enables Telic to:
- Alert on important mentions (@user, keywords)
- Monitor channels for important updates
- Send messages on user's behalf (with approval)
- Cross-reference Slack threads with Jira/GitHub
- Prepare for meetings from Slack context
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import json

import httpx

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class SlackUser:
    """Slack user information."""
    id: str
    name: str  # username
    real_name: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    is_bot: bool = False
    is_admin: bool = False
    status_text: Optional[str] = None
    status_emoji: Optional[str] = None
    timezone: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "SlackUser":
        profile = data.get("profile", {})
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            real_name=profile.get("real_name") or data.get("real_name"),
            display_name=profile.get("display_name"),
            email=profile.get("email"),
            avatar_url=profile.get("image_72"),
            is_bot=data.get("is_bot", False),
            is_admin=data.get("is_admin", False),
            status_text=profile.get("status_text"),
            status_emoji=profile.get("status_emoji"),
            timezone=data.get("tz"),
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "real_name": self.real_name,
            "display_name": self.display_name,
            "email": self.email,
            "is_bot": self.is_bot,
            "status": f"{self.status_emoji} {self.status_text}".strip() if self.status_emoji or self.status_text else None,
        }


@dataclass
class SlackChannel:
    """Slack channel information."""
    id: str
    name: str
    is_private: bool = False
    is_archived: bool = False
    is_member: bool = False
    topic: Optional[str] = None
    purpose: Optional[str] = None
    num_members: int = 0
    created: Optional[datetime] = None
    
    @classmethod
    def from_api(cls, data: Dict) -> "SlackChannel":
        created = data.get("created")
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            is_private=data.get("is_private", False),
            is_archived=data.get("is_archived", False),
            is_member=data.get("is_member", False),
            topic=data.get("topic", {}).get("value"),
            purpose=data.get("purpose", {}).get("value"),
            num_members=data.get("num_members", 0),
            created=datetime.fromtimestamp(created) if created else None,
        )
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_private": self.is_private,
            "is_archived": self.is_archived,
            "is_member": self.is_member,
            "topic": self.topic,
            "num_members": self.num_members,
        }


@dataclass
class SlackMessage:
    """Slack message information."""
    ts: str  # Timestamp (also serves as unique ID)
    text: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    channel_id: Optional[str] = None
    channel_name: Optional[str] = None
    thread_ts: Optional[str] = None  # If in a thread
    reply_count: int = 0
    reactions: List[Dict] = field(default_factory=list)
    files: List[Dict] = field(default_factory=list)
    mentions: List[str] = field(default_factory=list)  # User IDs mentioned
    timestamp: Optional[datetime] = None
    permalink: Optional[str] = None
    
    @classmethod
    def from_api(cls, data: Dict, channel_name: str = None) -> "SlackMessage":
        ts = data.get("ts", "")
        timestamp = None
        if ts:
            try:
                timestamp = datetime.fromtimestamp(float(ts))
            except:
                pass
        
        # Extract mentions from text
        text = data.get("text", "")
        mentions = []
        if "<@" in text:
            import re
            mentions = re.findall(r"<@([A-Z0-9]+)>", text)
        
        return cls(
            ts=ts,
            text=text,
            user_id=data.get("user"),
            channel_id=data.get("channel"),
            channel_name=channel_name,
            thread_ts=data.get("thread_ts"),
            reply_count=data.get("reply_count", 0),
            reactions=data.get("reactions", []),
            files=[{"name": f.get("name"), "url": f.get("url_private")} for f in data.get("files", [])],
            mentions=mentions,
            timestamp=timestamp,
            permalink=data.get("permalink"),
        )
    
    def to_dict(self) -> Dict:
        return {
            "ts": self.ts,
            "text": self.text[:200] + "..." if len(self.text) > 200 else self.text,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "thread_ts": self.thread_ts,
            "reply_count": self.reply_count,
            "reactions": [r.get("name") for r in self.reactions],
            "has_files": len(self.files) > 0,
            "mentions": self.mentions,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class SlackNotification:
    """Slack notification (mention, DM, etc.)."""
    id: str
    channel_id: str
    channel_name: str
    message: SlackMessage
    notification_type: str  # mention, dm, reaction, thread_reply
    is_dm: bool = False
    is_mention: bool = False
    is_unread: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "type": self.notification_type,
            "is_dm": self.is_dm,
            "is_mention": self.is_mention,
            "message": self.message.to_dict() if self.message else None,
        }


# ============================================================================
# Slack Connector
# ============================================================================

class SlackConnector:
    """
    Slack API connector for workplace communication integration.
    
    Authentication:
    - SLACK_BOT_TOKEN: Bot User OAuth Token (xoxb-...)
    - SLACK_USER_TOKEN: User OAuth Token (xoxp-...) - for some operations
    
    Get tokens from: https://api.slack.com/apps
    
    Required scopes for bot token:
    - channels:read, channels:history, channels:join
    - chat:write, chat:write.public
    - users:read, users:read.email
    - search:read
    - files:read
    - reactions:read
    - im:read, im:history (for DMs)
    - mpim:read, mpim:history (for group DMs)
    
    Usage:
        connector = SlackConnector(token="xoxb-...")
        await connector.connect()
        
        # List channels
        channels = await connector.list_channels()
        
        # Send a message
        await connector.send_message("#general", "Hello from Telic!")
    """
    
    def __init__(
        self,
        token: Optional[str] = None,
        user_token: Optional[str] = None,  # For user-specific operations
    ):
        self._token = token or os.environ.get("SLACK_BOT_TOKEN", "")
        self._user_token = user_token or os.environ.get("SLACK_USER_TOKEN", "")
        self._client: Optional[httpx.AsyncClient] = None
        self._user: Optional[SlackUser] = None
        self._team: Optional[Dict] = None
        self._connected = False
        self._users_cache: Dict[str, SlackUser] = {}
        self._channels_cache: Dict[str, SlackChannel] = {}
    
    async def connect(self) -> bool:
        """Connect to Slack API."""
        if not self._token:
            logger.error("Missing Slack token. Set SLACK_BOT_TOKEN environment variable.")
            return False
        
        self._client = httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=30.0,
        )
        
        # Test authentication
        try:
            data = await self._post("auth.test")
            if not data.get("ok"):
                logger.error(f"Slack auth failed: {data.get('error')}")
                await self._client.aclose()
                self._client = None
                return False
            
            self._team = {
                "id": data.get("team_id"),
                "name": data.get("team"),
                "url": data.get("url"),
            }
            
            # Get bot user info
            user_data = await self._get("users.info", {"user": data.get("user_id")})
            if user_data.get("ok"):
                self._user = SlackUser.from_api(user_data.get("user", {}))
            
            self._connected = True
            logger.info(f"Connected to Slack workspace: {self._team.get('name')}")
            return True
            
        except Exception as e:
            logger.error(f"Slack connection failed: {e}")
            if self._client:
                await self._client.aclose()
                self._client = None
            return False
    
    async def disconnect(self):
        """Disconnect from Slack API."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False
        self._user = None
        self._team = None
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @property
    def current_user(self) -> Optional[SlackUser]:
        return self._user
    
    @property
    def team(self) -> Optional[Dict]:
        return self._team

    async def health_check(self) -> str:
        """Check Slack API connectivity. Returns 'healthy', 'auth_required', or 'unhealthy'."""
        if not self._client:
            return "disconnected"
        try:
            data = await self._post("auth.test")
            if data.get("ok"):
                return "healthy"
            if data.get("error") in ("invalid_auth", "token_revoked", "not_authed"):
                return "auth_required"
            return "unhealthy"
        except Exception:
            return "unhealthy"
    
    # === API Methods ===
    
    async def _get(self, endpoint: str, params: Dict = None) -> Dict:
        """Make GET request to Slack API."""
        if not self._client:
            raise RuntimeError("Not connected to Slack")
        
        response = await self._client.get(f"/{endpoint}", params=params)
        return response.json()
    
    async def _post(self, endpoint: str, data: Dict = None) -> Dict:
        """Make POST request to Slack API."""
        if not self._client:
            raise RuntimeError("Not connected to Slack")
        
        response = await self._client.post(f"/{endpoint}", json=data or {})
        return response.json()
    
    # === Channels ===
    
    async def list_channels(
        self,
        exclude_archived: bool = True,
        limit: int = 100,
    ) -> List[SlackChannel]:
        """List public channels in the workspace."""
        data = await self._get("conversations.list", {
            "exclude_archived": str(exclude_archived).lower(),
            "limit": limit,
            "types": "public_channel,private_channel",
        })
        
        if not data.get("ok"):
            logger.error(f"Failed to list channels: {data.get('error')}")
            return []
        
        channels = [SlackChannel.from_api(c) for c in data.get("channels", [])]
        
        # Update cache
        for c in channels:
            self._channels_cache[c.id] = c
        
        return channels
    
    async def get_channel(self, channel_id: str) -> Optional[SlackChannel]:
        """Get channel info."""
        if channel_id in self._channels_cache:
            return self._channels_cache[channel_id]
        
        data = await self._get("conversations.info", {"channel": channel_id})
        
        if not data.get("ok"):
            return None
        
        channel = SlackChannel.from_api(data.get("channel", {}))
        self._channels_cache[channel_id] = channel
        return channel
    
    async def join_channel(self, channel_id: str) -> bool:
        """Join a public channel."""
        data = await self._post("conversations.join", {"channel": channel_id})
        return data.get("ok", False)
    
    # === Messages ===
    
    async def send_message(
        self,
        channel: str,  # Channel ID or name (with #)
        text: str,
        thread_ts: str = None,
        blocks: List[Dict] = None,
    ) -> Optional[str]:
        """
        Send a message to a channel.
        
        Returns the message timestamp (ts) on success.
        """
        # Resolve channel name to ID if needed
        if channel.startswith("#"):
            channels = await self.list_channels()
            channel_obj = next((c for c in channels if c.name == channel[1:]), None)
            if not channel_obj:
                logger.error(f"Channel not found: {channel}")
                return None
            channel = channel_obj.id
        
        payload = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks
        
        data = await self._post("chat.postMessage", payload)
        
        if not data.get("ok"):
            logger.error(f"Failed to send message: {data.get('error')}")
            return None
        
        return data.get("ts")
    
    async def get_channel_history(
        self,
        channel: str,
        limit: int = 50,
        oldest: str = None,
        latest: str = None,
    ) -> List[SlackMessage]:
        """Get recent messages from a channel."""
        params = {
            "channel": channel,
            "limit": limit,
        }
        if oldest:
            params["oldest"] = oldest
        if latest:
            params["latest"] = latest
        
        data = await self._get("conversations.history", params)
        
        if not data.get("ok"):
            logger.error(f"Failed to get history: {data.get('error')}")
            return []
        
        channel_obj = await self.get_channel(channel)
        channel_name = channel_obj.name if channel_obj else None
        
        return [SlackMessage.from_api(m, channel_name) for m in data.get("messages", [])]
    
    async def search_messages(
        self,
        query: str,
        count: int = 20,
        sort: str = "timestamp",  # timestamp or score
    ) -> List[SlackMessage]:
        """
        Search messages across all channels.
        
        Note: Requires search:read scope.
        """
        data = await self._get("search.messages", {
            "query": query,
            "count": count,
            "sort": sort,
        })
        
        if not data.get("ok"):
            logger.error(f"Search failed: {data.get('error')}")
            return []
        
        messages = []
        for match in data.get("messages", {}).get("matches", []):
            msg = SlackMessage.from_api(match)
            msg.channel_name = match.get("channel", {}).get("name")
            msg.user_name = match.get("username")
            msg.permalink = match.get("permalink")
            messages.append(msg)
        
        return messages
    
    async def add_reaction(self, channel: str, timestamp: str, emoji: str) -> bool:
        """Add a reaction to a message."""
        data = await self._post("reactions.add", {
            "channel": channel,
            "timestamp": timestamp,
            "name": emoji.strip(":"),  # Remove colons if present
        })
        return data.get("ok", False)
    
    # === Users ===
    
    async def get_user(self, user_id: str) -> Optional[SlackUser]:
        """Get user info by ID."""
        if user_id in self._users_cache:
            return self._users_cache[user_id]
        
        data = await self._get("users.info", {"user": user_id})
        
        if not data.get("ok"):
            return None
        
        user = SlackUser.from_api(data.get("user", {}))
        self._users_cache[user_id] = user
        return user
    
    async def list_users(self, limit: int = 100) -> List[SlackUser]:
        """List users in the workspace."""
        data = await self._get("users.list", {"limit": limit})
        
        if not data.get("ok"):
            return []
        
        users = [SlackUser.from_api(u) for u in data.get("members", []) if not u.get("deleted")]
        
        for u in users:
            self._users_cache[u.id] = u
        
        return users
    
    async def find_user_by_email(self, email: str) -> Optional[SlackUser]:
        """Find a user by email address."""
        data = await self._get("users.lookupByEmail", {"email": email})
        
        if not data.get("ok"):
            return None
        
        return SlackUser.from_api(data.get("user", {}))
    
    # === Notifications / Mentions ===
    
    async def get_mentions(self, limit: int = 50) -> List[SlackMessage]:
        """
        Get recent messages mentioning the bot/user.
        
        Note: Uses search API to find mentions.
        """
        if not self._user:
            return []
        
        # Search for mentions of the bot
        query = f"<@{self._user.id}>"
        return await self.search_messages(query, count=limit)
    
    async def get_dms(self, limit: int = 20) -> List[Dict]:
        """Get recent direct message conversations."""
        data = await self._get("conversations.list", {
            "types": "im",
            "limit": limit,
        })
        
        if not data.get("ok"):
            return []
        
        dms = []
        for conv in data.get("channels", []):
            user_id = conv.get("user")
            user = await self.get_user(user_id) if user_id else None
            
            # Get latest message
            history = await self.get_channel_history(conv.get("id"), limit=1)
            
            dms.append({
                "channel_id": conv.get("id"),
                "user": user.to_dict() if user else {"id": user_id},
                "latest_message": history[0].to_dict() if history else None,
            })
        
        return dms
    
    # === Status ===
    
    async def set_status(self, text: str, emoji: str = "", expiration: int = 0) -> bool:
        """
        Set the user's status.
        
        Note: Requires user token, not bot token.
        """
        # This requires user token
        if not self._user_token:
            logger.warning("Setting status requires user token (SLACK_USER_TOKEN)")
            return False
        
        # Create client with user token
        async with httpx.AsyncClient(
            base_url="https://slack.com/api",
            headers={"Authorization": f"Bearer {self._user_token}"},
        ) as client:
            response = await client.post("/users.profile.set", json={
                "profile": {
                    "status_text": text,
                    "status_emoji": emoji,
                    "status_expiration": expiration,
                }
            })
            data = response.json()
            return data.get("ok", False)
    
    # === Activity Summary (for proactive monitoring) ===
    
    async def get_activity_summary(self) -> Dict:
        """
        Get a summary of Slack activity for the user.
        
        Useful for proactive alerts and daily briefings.
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "team": self._team.get("name") if self._team else None,
            "user": self._user.name if self._user else None,
            "mentions": [],
            "unread_dms": [],
            "channels": [],
        }
        
        try:
            # Recent mentions
            mentions = await self.get_mentions(limit=10)
            summary["mentions"] = [m.to_dict() for m in mentions]
            
            # DMs
            dms = await self.get_dms(limit=10)
            summary["unread_dms"] = dms
            
            # Joined channels
            channels = await self.list_channels()
            summary["channels"] = [c.to_dict() for c in channels if c.is_member]
            
        except Exception as e:
            logger.error(f"Error getting Slack activity summary: {e}")
            summary["error"] = str(e)
        
        return summary
    
    # === Polling for ProactiveMonitor ===
    
    async def get_recent(self) -> Dict:
        """Get recent activity for proactive monitoring."""
        return await self.get_activity_summary()
    
    async def poll(self) -> Dict:
        """Alias for get_recent (ProactiveMonitor compatibility)."""
        return await self.get_recent()


# ============================================================================
# Factory Function
# ============================================================================

def create_slack_connector(
    token: Optional[str] = None,
    user_token: Optional[str] = None,
) -> SlackConnector:
    """Create a new SlackConnector instance."""
    return SlackConnector(token=token, user_token=user_token)
