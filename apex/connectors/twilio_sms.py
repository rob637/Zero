"""
Twilio SMS Connector - SMS/MMS Messaging Integration

Provides SMS and MMS messaging via the Twilio REST API.

Capabilities:
- Send SMS/MMS messages
- List recent messages
- Check message status/delivery
- Receive messages (via webhook)

Setup:
    from connectors.twilio_sms import TwilioSMSConnector
    
    sms = TwilioSMSConnector(
        account_sid="AC...",
        auth_token="...",
        from_number="+1234567890",
    )
    
    await sms.send(to="+1987654321", body="Hello!")
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SMSMessage:
    """SMS message."""
    sid: str
    to: str
    from_number: str
    body: str
    status: str
    direction: str
    date_sent: Optional[str] = None

    @classmethod
    def from_api(cls, data: Dict) -> "SMSMessage":
        return cls(
            sid=data.get("sid", ""),
            to=data.get("to", ""),
            from_number=data.get("from", ""),
            body=data.get("body", ""),
            status=data.get("status", ""),
            direction=data.get("direction", ""),
            date_sent=data.get("date_sent"),
        )


class TwilioSMSConnector:
    """Twilio SMS/MMS connector."""

    BASE_URL = "https://api.twilio.com/2010-04-01"

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
    ):
        self._sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID", "")
        self._token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN", "")
        self._from = from_number or os.environ.get("TWILIO_FROM_NUMBER", "")
        self._http = None

    async def connect(self):
        """Initialize HTTP client."""
        if not self._sid or not self._token:
            raise ValueError(
                "Twilio credentials required. Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN."
            )

        import httpx
        self._http = httpx.AsyncClient(
            base_url=f"{self.BASE_URL}/Accounts/{self._sid}",
            auth=(self._sid, self._token),
            timeout=30,
        )

    async def _ensure_client(self):
        if not self._http:
            await self.connect()

    async def send(
        self, to: str, body: str, media_url: Optional[str] = None
    ) -> SMSMessage:
        """Send an SMS or MMS message."""
        await self._ensure_client()

        data = {
            "To": to,
            "From": self._from,
            "Body": body,
        }
        if media_url:
            data["MediaUrl"] = media_url

        resp = await self._http.post(
            "/Messages.json",
            data=data,
        )
        resp.raise_for_status()
        return SMSMessage.from_api(resp.json())

    async def list_messages(
        self, limit: int = 20, to: Optional[str] = None, from_number: Optional[str] = None
    ) -> List[SMSMessage]:
        """List recent messages."""
        await self._ensure_client()

        params = {"PageSize": min(limit, 100)}
        if to:
            params["To"] = to
        if from_number:
            params["From"] = from_number

        resp = await self._http.get("/Messages.json", params=params)
        resp.raise_for_status()
        return [SMSMessage.from_api(m) for m in resp.json().get("messages", [])]

    async def get_message(self, message_sid: str) -> SMSMessage:
        """Get a specific message by SID."""
        await self._ensure_client()
        resp = await self._http.get(f"/Messages/{message_sid}.json")
        resp.raise_for_status()
        return SMSMessage.from_api(resp.json())

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None
