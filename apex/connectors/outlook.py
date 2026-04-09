"""
Outlook Mail Connector (Microsoft Graph API)

Full Microsoft Outlook email integration:
- List and search messages
- Send emails with attachments
- Create drafts
- Manage folders
- Read message content
- Move/delete messages

Usage:
    from connectors.outlook import OutlookConnector
    
    outlook = OutlookConnector()
    await outlook.connect()
    
    # List recent emails
    emails = await outlook.list_messages(max_results=10)
    
    # Send email
    await outlook.send_email(
        to=["fred@example.com"],
        subject="Hello",
        body="Hi Fred!"
    )
    
    # Search
    emails = await outlook.search("from:alice@example.com")
"""

import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, BinaryIO

from .microsoft_graph import GraphClient, get_graph_client, GraphAPIError

import logging
logger = logging.getLogger(__name__)


@dataclass
class OutlookEmail:
    """Represents an Outlook email message."""
    id: str
    conversation_id: str
    subject: str
    sender: Dict  # {name, email}
    to_recipients: List[Dict]  # [{name, email}, ...]
    cc_recipients: List[Dict]
    received_datetime: Optional[datetime]
    sent_datetime: Optional[datetime]
    body_preview: str
    body_content: Optional[str] = None
    body_type: str = "text"  # text or html
    importance: str = "normal"
    is_read: bool = True
    is_draft: bool = False
    has_attachments: bool = False
    attachments: List[Dict] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    web_link: Optional[str] = None
    
    @property
    def sender_email(self) -> str:
        return self.sender.get('email', '')
    
    @property
    def sender_name(self) -> str:
        return self.sender.get('name', '')
    
    def to_dict(self) -> Dict:
        d = {
            "id": self.id,
            "subject": self.subject,
            "sender": f"{self.sender_name} <{self.sender_email}>",
            "to": [f"{r.get('name', '')} <{r.get('email', '')}>".strip() for r in self.to_recipients],
            "date": self.received_datetime.isoformat() if self.received_datetime else None,
            "snippet": self.body_preview,
        }
        if not self.is_read:
            d["unread"] = True
        if self.has_attachments:
            d["has_attachments"] = True
        if self.body_content:
            d["body"] = self.body_content
        if self.importance != "normal":
            d["importance"] = self.importance
        return d


class OutlookConnector:
    """
    Microsoft Outlook email connector via Graph API.
    
    Provides full email functionality:
    - List, search, read messages
    - Send emails with attachments
    - Create and manage drafts
    - Folder management
    - Mark read/unread
    - Move/delete messages
    """
    
    def __init__(self, client: Optional[GraphClient] = None):
        self._client = client or get_graph_client()
        self._user_email: Optional[str] = None
        self._connected = False
    
    async def connect(self) -> bool:
        """Connect to Outlook via Microsoft Graph API."""
        if not self._client.connected:
            success = await self._client.connect(['mail'])
            if not success:
                return False
        
        # Get user info
        try:
            user = await self._client.get_user_info()
            self._user_email = user.get('mail') or user.get('userPrincipalName')
            self._connected = True
            return True
        except GraphAPIError as e:
            logger.error(f"Failed to get user info: {e}")
            return False
    
    @property
    def connected(self) -> bool:
        return self._connected
    
    @property
    def user_email(self) -> Optional[str]:
        return self._user_email
    
    def _parse_message(self, msg: Dict, include_body: bool = False) -> OutlookEmail:
        """Parse Graph API message into OutlookEmail."""
        sender = msg.get('from', {}).get('emailAddress', {})
        
        def parse_recipients(key):
            return [
                {
                    'name': r.get('emailAddress', {}).get('name', ''),
                    'email': r.get('emailAddress', {}).get('address', ''),
                }
                for r in msg.get(key, [])
            ]
        
        # Parse datetime
        received = msg.get('receivedDateTime')
        sent = msg.get('sentDateTime')
        
        try:
            received_dt = datetime.fromisoformat(received.replace('Z', '+00:00')) if received else None
        except:
            received_dt = None
        
        try:
            sent_dt = datetime.fromisoformat(sent.replace('Z', '+00:00')) if sent else None
        except:
            sent_dt = None
        
        # Parse body
        body = msg.get('body', {})
        body_content = body.get('content') if include_body else None
        body_type = body.get('contentType', 'text').lower()
        
        return OutlookEmail(
            id=msg.get('id', ''),
            conversation_id=msg.get('conversationId', ''),
            subject=msg.get('subject', '(No Subject)'),
            sender={
                'name': sender.get('name', ''),
                'email': sender.get('address', ''),
            },
            to_recipients=parse_recipients('toRecipients'),
            cc_recipients=parse_recipients('ccRecipients'),
            received_datetime=received_dt,
            sent_datetime=sent_dt,
            body_preview=msg.get('bodyPreview', ''),
            body_content=body_content,
            body_type=body_type,
            importance=msg.get('importance', 'normal'),
            is_read=msg.get('isRead', True),
            is_draft=msg.get('isDraft', False),
            has_attachments=msg.get('hasAttachments', False),
            categories=msg.get('categories', []),
            web_link=msg.get('webLink'),
        )
    
    async def list_messages(
        self,
        folder: str = "inbox",
        max_results: int = 25,
        filter_query: str = None,
        search_query: str = None,
        include_body: bool = False,
        unread_only: bool = False,
    ) -> List[OutlookEmail]:
        """
        List email messages.
        
        Args:
            folder: Folder name (inbox, sentitems, drafts, deleteditems, etc.)
            max_results: Maximum messages to return
            filter_query: OData filter (e.g., "isRead eq false")
            search_query: Full-text search query
            include_body: Whether to include full message body
            unread_only: Only return unread messages
        
        Returns:
            List of OutlookEmail objects
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Build endpoint
        endpoint = f"/me/mailFolders/{folder}/messages"
        
        params = {
            '$top': max_results,
            '$orderby': 'receivedDateTime desc',
            '$select': 'id,conversationId,subject,from,toRecipients,ccRecipients,'
                      'receivedDateTime,sentDateTime,bodyPreview,importance,'
                      'isRead,isDraft,hasAttachments,categories,webLink',
        }
        
        if include_body:
            params['$select'] += ',body'
        
        # Build filter
        filters = []
        if filter_query:
            filters.append(filter_query)
        if unread_only:
            filters.append("isRead eq false")
        
        if filters:
            params['$filter'] = ' and '.join(filters)
        
        if search_query:
            params['$search'] = f'"{search_query}"'
        
        try:
            result = await self._client.get(endpoint, params=params, scopes=['mail'])
            messages = result.get('value', [])
            return [self._parse_message(m, include_body) for m in messages]
        except GraphAPIError as e:
            logger.error(f"Failed to list messages: {e}")
            raise
    
    async def get_message(self, message_id: str) -> OutlookEmail:
        """
        Get a single message by ID with full content.
        
        Args:
            message_id: The message ID
        
        Returns:
            OutlookEmail with full body content
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self._client.get(
            f"/me/messages/{message_id}",
            params={'$select': '*'},
            scopes=['mail'],
        )
        
        # Get attachments if present
        email = self._parse_message(result, include_body=True)
        
        if email.has_attachments:
            attachments = await self._client.get(
                f"/me/messages/{message_id}/attachments",
                scopes=['mail'],
            )
            email.attachments = [
                {
                    'id': a.get('id'),
                    'name': a.get('name'),
                    'content_type': a.get('contentType'),
                    'size': a.get('size'),
                }
                for a in attachments.get('value', [])
            ]
        
        return email
    
    async def search(
        self,
        query: str,
        max_results: int = 25,
        folder: str = None,
    ) -> List[OutlookEmail]:
        """
        Search emails using OData search.
        
        Supports queries like:
        - "from:alice@example.com"
        - "subject:meeting"
        - "has:attachment"
        - Free text search
        
        Args:
            query: Search query
            max_results: Maximum results
            folder: Specific folder or None for all
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        if folder:
            endpoint = f"/me/mailFolders/{folder}/messages"
        else:
            endpoint = "/me/messages"
        
        params = {
            '$top': max_results,
            '$orderby': 'receivedDateTime desc',
            '$search': f'"{query}"',
            '$select': 'id,conversationId,subject,from,toRecipients,'
                      'receivedDateTime,bodyPreview,importance,isRead,'
                      'hasAttachments,categories',
        }
        
        result = await self._client.get(endpoint, params=params, scopes=['mail'])
        return [self._parse_message(m) for m in result.get('value', [])]
    
    async def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: List[str] = None,
        bcc: List[str] = None,
        html: bool = False,
        attachments: List[str] = None,
        importance: str = "normal",
        save_to_sent: bool = True,
    ) -> Dict:
        """
        Send an email.
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body (text or HTML)
            cc: CC recipients
            bcc: BCC recipients
            html: Whether body is HTML
            attachments: List of file paths to attach
            importance: low, normal, or high
            save_to_sent: Save copy to Sent folder
        
        Returns:
            Dict with success status
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        def make_recipient(email: str) -> Dict:
            # Handle "Name <email>" format
            if '<' in email and '>' in email:
                name = email[:email.index('<')].strip()
                addr = email[email.index('<')+1:email.index('>')].strip()
            else:
                name = ""
                addr = email.strip()
            return {
                "emailAddress": {
                    "address": addr,
                    "name": name,
                }
            }
        
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML" if html else "Text",
                "content": body,
            },
            "toRecipients": [make_recipient(e) for e in to],
            "importance": importance,
        }
        
        if cc:
            message["ccRecipients"] = [make_recipient(e) for e in cc]
        if bcc:
            message["bccRecipients"] = [make_recipient(e) for e in bcc]
        
        # Handle attachments
        if attachments:
            message["attachments"] = []
            for filepath in attachments:
                path = Path(filepath).expanduser()
                if path.exists():
                    with open(path, 'rb') as f:
                        content = base64.b64encode(f.read()).decode('utf-8')
                    message["attachments"].append({
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": path.name,
                        "contentBytes": content,
                    })
        
        # Send
        try:
            await self._client.post(
                "/me/sendMail",
                json_data={
                    "message": message,
                    "saveToSentItems": save_to_sent,
                },
                scopes=['mail'],
            )
            return {"success": True, "to": to, "subject": subject}
        except GraphAPIError as e:
            logger.error(f"Failed to send email: {e}")
            raise
    
    async def create_draft(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: List[str] = None,
        html: bool = False,
    ) -> OutlookEmail:
        """
        Create a draft email.
        
        Returns:
            Created draft as OutlookEmail
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        def make_recipient(email: str) -> Dict:
            return {"emailAddress": {"address": email.strip()}}
        
        draft = {
            "subject": subject,
            "body": {
                "contentType": "HTML" if html else "Text",
                "content": body,
            },
            "toRecipients": [make_recipient(e) for e in to],
        }
        
        if cc:
            draft["ccRecipients"] = [make_recipient(e) for e in cc]
        
        result = await self._client.post("/me/messages", json_data=draft, scopes=['mail'])
        return self._parse_message(result, include_body=True)
    
    async def reply(
        self,
        message_id: str,
        body: str,
        reply_all: bool = False,
    ) -> Dict:
        """
        Reply to a message.
        
        Args:
            message_id: Original message ID
            body: Reply body
            reply_all: Reply to all recipients
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        endpoint = f"/me/messages/{message_id}/{'replyAll' if reply_all else 'reply'}"
        
        await self._client.post(
            endpoint,
            json_data={"comment": body},
            scopes=['mail'],
        )
        
        return {"success": True, "replied_to": message_id}
    
    async def forward(
        self,
        message_id: str,
        to: List[str],
        comment: str = None,
    ) -> Dict:
        """Forward a message."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        def make_recipient(email: str) -> Dict:
            return {"emailAddress": {"address": email.strip()}}
        
        await self._client.post(
            f"/me/messages/{message_id}/forward",
            json_data={
                "toRecipients": [make_recipient(e) for e in to],
                "comment": comment or "",
            },
            scopes=['mail'],
        )
        
        return {"success": True, "forwarded_to": to}
    
    async def mark_read(self, message_id: str) -> bool:
        """Mark a message as read."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        await self._client.patch(
            f"/me/messages/{message_id}",
            json_data={"isRead": True},
            scopes=['mail'],
        )
        return True
    
    async def mark_unread(self, message_id: str) -> bool:
        """Mark a message as unread."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        await self._client.patch(
            f"/me/messages/{message_id}",
            json_data={"isRead": False},
            scopes=['mail'],
        )
        return True
    
    async def move_message(self, message_id: str, folder: str) -> bool:
        """
        Move a message to a different folder.
        
        Args:
            message_id: Message ID
            folder: Destination folder ID or well-known name
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        await self._client.post(
            f"/me/messages/{message_id}/move",
            json_data={"destinationId": folder},
            scopes=['mail'],
        )
        return True
    
    async def delete_message(self, message_id: str) -> bool:
        """Delete a message (moves to Deleted Items)."""
        return await self.move_message(message_id, "deleteditems")
    
    async def get_folders(self) -> List[Dict]:
        """Get all mail folders."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self._client.get("/me/mailFolders", scopes=['mail'])
        
        return [
            {
                'id': f.get('id'),
                'name': f.get('displayName'),
                'unread_count': f.get('unreadItemCount', 0),
                'total_count': f.get('totalItemCount', 0),
            }
            for f in result.get('value', [])
        ]
    
    async def get_attachment(
        self,
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        """
        Download an attachment.
        
        Returns:
            Attachment content as bytes
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")
        
        result = await self._client.get(
            f"/me/messages/{message_id}/attachments/{attachment_id}",
            scopes=['mail'],
        )
        
        content = result.get('contentBytes', '')
        return base64.b64decode(content)
