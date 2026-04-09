"""
Telegram Connector - Telegram Bot API

Send messages, manage chats, and interact via Telegram Bot API.

Setup:
    1. Message @BotFather on Telegram → /newbot
    2. Copy the bot token
    
    export TELEGRAM_BOT_TOKEN="your-bot-token"

    from connectors.telegram import TelegramConnector
    telegram = TelegramConnector(bot_token="...")
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.telegram.org"


class TelegramConnector:
    """Telegram messaging via Bot API."""

    def __init__(self, bot_token: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.connected = bool(self.bot_token)

    async def connect(self) -> bool:
        """Validate Telegram bot token."""
        self.connected = bool(self.bot_token)
        return self.connected

    @property
    def _api(self) -> str:
        return f"{BASE_URL}/bot{self.bot_token}"

    async def _get(self, method: str, params: Optional[Dict] = None) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{self._api}/{method}", params=params or {})
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", "Telegram API error"))
            return data.get("result")

    async def _post(self, method: str, data: Optional[Dict] = None) -> Any:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self._api}/{method}",
                json=data or {},
            )
            resp.raise_for_status()
            result = resp.json()
            if not result.get("ok"):
                raise RuntimeError(result.get("description", "Telegram API error"))
            return result.get("result")

    # ── Bot Info ──

    async def me(self) -> Dict:
        """Get the bot's profile."""
        data = await self._get("getMe")
        return {
            "id": data.get("id"),
            "username": data.get("username", ""),
            "first_name": data.get("first_name", ""),
            "can_join_groups": data.get("can_join_groups", False),
            "can_read_messages": data.get("can_read_all_group_messages", False),
            "supports_inline": data.get("supports_inline_queries", False),
        }

    # ── Messages ──

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: Optional[str] = "Markdown",
        disable_notification: bool = False,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict:
        """Send a text message.
        
        Args:
            chat_id: Chat ID or @channel_username
            text: Message text (supports Markdown or HTML)
            parse_mode: 'Markdown', 'MarkdownV2', or 'HTML' (default: Markdown)
            disable_notification: Send silently
            reply_to_message_id: Reply to a specific message
        """
        body: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            body["parse_mode"] = parse_mode
        if disable_notification:
            body["disable_notification"] = True
        if reply_to_message_id:
            body["reply_to_message_id"] = reply_to_message_id

        data = await self._post("sendMessage", body)
        return self._parse_message(data)

    async def forward_message(
        self,
        chat_id: str,
        from_chat_id: str,
        message_id: int,
    ) -> Dict:
        """Forward a message from one chat to another.
        
        Args:
            chat_id: Target chat ID
            from_chat_id: Source chat ID
            message_id: Message ID to forward
        """
        data = await self._post("forwardMessage", {
            "chat_id": chat_id,
            "from_chat_id": from_chat_id,
            "message_id": message_id,
        })
        return self._parse_message(data)

    async def edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = "Markdown",
    ) -> Dict:
        """Edit a sent message.
        
        Args:
            chat_id: Chat ID
            message_id: Message ID to edit
            text: New text
            parse_mode: 'Markdown', 'MarkdownV2', or 'HTML'
        """
        body: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            body["parse_mode"] = parse_mode
        data = await self._post("editMessageText", body)
        return self._parse_message(data)

    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        """Delete a message.
        
        Args:
            chat_id: Chat ID
            message_id: Message ID to delete
        """
        await self._post("deleteMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })
        return True

    async def send_photo(
        self,
        chat_id: str,
        photo_url: str,
        caption: Optional[str] = None,
    ) -> Dict:
        """Send a photo by URL.
        
        Args:
            chat_id: Chat ID
            photo_url: Photo URL
            caption: Photo caption
        """
        body: Dict[str, Any] = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            body["caption"] = caption
        data = await self._post("sendPhoto", body)
        return self._parse_message(data)

    async def send_document(
        self,
        chat_id: str,
        document_url: str,
        caption: Optional[str] = None,
    ) -> Dict:
        """Send a document/file by URL.
        
        Args:
            chat_id: Chat ID
            document_url: Document URL
            caption: Document caption
        """
        body: Dict[str, Any] = {"chat_id": chat_id, "document": document_url}
        if caption:
            body["caption"] = caption
        data = await self._post("sendDocument", body)
        return self._parse_message(data)

    # ── Chat ──

    async def get_chat(self, chat_id: str) -> Dict:
        """Get chat info.
        
        Args:
            chat_id: Chat ID or @username
        """
        data = await self._get("getChat", {"chat_id": chat_id})
        result: Dict[str, Any] = {
            "id": data.get("id"),
            "type": data.get("type", ""),
            "title": data.get("title", ""),
        }
        if data.get("username"):
            result["username"] = data["username"]
        if data.get("description"):
            result["description"] = data["description"][:500]
        if data.get("invite_link"):
            result["invite_link"] = data["invite_link"]
        return result

    async def get_chat_member_count(self, chat_id: str) -> int:
        """Get number of members in a chat.
        
        Args:
            chat_id: Chat ID
        """
        return await self._get("getChatMemberCount", {"chat_id": chat_id})

    async def get_updates(self, limit: int = 10, offset: Optional[int] = None) -> List[Dict]:
        """Get recent bot updates (incoming messages).
        
        Args:
            limit: Max updates (default 10)
            offset: Update offset for pagination
        """
        params: Dict[str, Any] = {"limit": limit}
        if offset is not None:
            params["offset"] = offset
        data = await self._get("getUpdates", params)
        updates = []
        for u in data:
            update: Dict[str, Any] = {"update_id": u.get("update_id")}
            if u.get("message"):
                update["message"] = self._parse_message(u["message"])
            if u.get("callback_query"):
                cq = u["callback_query"]
                update["callback"] = {
                    "id": cq.get("id"),
                    "data": cq.get("data", ""),
                    "from": cq.get("from", {}).get("first_name", ""),
                }
            updates.append(update)
        return updates

    # ── Pin/Unpin ──

    async def pin_message(self, chat_id: str, message_id: int) -> bool:
        """Pin a message in a chat.
        
        Args:
            chat_id: Chat ID
            message_id: Message ID to pin
        """
        await self._post("pinChatMessage", {
            "chat_id": chat_id,
            "message_id": message_id,
        })
        return True

    async def unpin_message(self, chat_id: str, message_id: Optional[int] = None) -> bool:
        """Unpin a message or all pinned messages.
        
        Args:
            chat_id: Chat ID
            message_id: Specific message to unpin (omit to unpin all)
        """
        body: Dict[str, Any] = {"chat_id": chat_id}
        if message_id:
            body["message_id"] = message_id
            await self._post("unpinChatMessage", body)
        else:
            await self._post("unpinAllChatMessages", body)
        return True

    # ── Helpers ──

    def _parse_message(self, m: Dict) -> Dict:
        """Parse a message into a clean dict."""
        result: Dict[str, Any] = {
            "message_id": m.get("message_id"),
            "date": m.get("date"),
        }
        if m.get("text"):
            result["text"] = m["text"]
        if m.get("from"):
            f = m["from"]
            result["from"] = {
                "id": f.get("id"),
                "name": f"{f.get('first_name', '')} {f.get('last_name', '')}".strip(),
                "username": f.get("username", ""),
            }
        if m.get("chat"):
            c = m["chat"]
            result["chat"] = {
                "id": c.get("id"),
                "type": c.get("type", ""),
                "title": c.get("title", c.get("first_name", "")),
            }
        if m.get("caption"):
            result["caption"] = m["caption"]
        return result
