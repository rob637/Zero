"""
Gmail Connector

Real Gmail API integration for sending, reading, and searching emails.

Usage:
    from connectors.gmail import GmailConnector
    
    gmail = GmailConnector()
    await gmail.connect()
    
    # List recent emails
    emails = await gmail.list_messages(max_results=10)
    
    # Send email
    await gmail.send_email(
        to="fred@example.com",
        subject="Hello",
        body="Hi Fred!"
    )
"""

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Any, Dict, List, Optional

from .google_auth import GoogleAuth, get_google_auth

try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    HAS_GOOGLE_API = True
except ImportError:
    HAS_GOOGLE_API = False


@dataclass
class Email:
    """Represents an email message."""
    id: str
    thread_id: str
    subject: str
    sender: str
    to: List[str]
    date: datetime
    snippet: str
    body: Optional[str] = None
    labels: List[str] = None
    attachments: List[Dict] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "subject": self.subject,
            "sender": self.sender,
            "to": self.to,
            "date": self.date.isoformat() if self.date else None,
            "snippet": self.snippet,
            "body": self.body,
            "labels": self.labels or [],
            "attachments": self.attachments or [],
        }


class GmailConnector:
    """
    Gmail API connector.
    
    Provides methods for:
    - Listing and searching emails
    - Reading email content
    - Sending emails with attachments
    - Managing labels and drafts
    """
    
    def __init__(self, auth: Optional[GoogleAuth] = None):
        self._auth = auth or get_google_auth()
        self._service = None
        self._user_email: Optional[str] = None
    
    async def connect(self) -> bool:
        """
        Connect to Gmail API.
        
        Returns True if connected successfully.
        """
        if not HAS_GOOGLE_API:
            raise ImportError(
                "Google API client not installed. Run:\n"
                "pip install google-api-python-client"
            )
        
        creds = await self._auth.get_credentials(['gmail'])
        if not creds:
            return False
        
        # Build service in thread to avoid blocking
        self._service = await asyncio.to_thread(
            build, 'gmail', 'v1', credentials=creds
        )
        
        # Get user's email address
        try:
            profile = await asyncio.to_thread(
                self._service.users().getProfile(userId='me').execute
            )
            self._user_email = profile.get('emailAddress')
        except Exception:
            pass
        
        return True
    
    @property
    def connected(self) -> bool:
        return self._service is not None
    
    @property
    def user_email(self) -> Optional[str]:
        return self._user_email
    
    def _parse_message(self, msg: Dict, include_body: bool = False) -> Email:
        """Parse Gmail API message into Email object."""
        headers = {h['name'].lower(): h['value'] for h in msg.get('payload', {}).get('headers', [])}
        
        # Parse date
        date_str = headers.get('date', '')
        try:
            from email.utils import parsedate_to_datetime
            date = parsedate_to_datetime(date_str)
        except:
            date = datetime.now()
        
        # Parse body if requested
        body = None
        attachments = []
        
        if include_body:
            payload = msg.get('payload', {})
            body = self._extract_body(payload)
            attachments = self._extract_attachments(payload)
        
        # Parse recipients
        to_header = headers.get('to', '')
        to_list = [addr.strip() for addr in to_header.split(',') if addr.strip()]
        
        return Email(
            id=msg['id'],
            thread_id=msg.get('threadId', ''),
            subject=headers.get('subject', '(No Subject)'),
            sender=headers.get('from', ''),
            to=to_list,
            date=date,
            snippet=msg.get('snippet', ''),
            body=body,
            labels=msg.get('labelIds', []),
            attachments=attachments,
        )
    
    def _extract_body(self, payload: Dict) -> str:
        """Extract email body from payload."""
        body = ""
        
        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
        
        elif 'parts' in payload:
            for part in payload['parts']:
                mime_type = part.get('mimeType', '')
                if mime_type == 'text/plain':
                    if part['body'].get('data'):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                        break
                elif mime_type == 'text/html' and not body:
                    if part['body'].get('data'):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    body = self._extract_body(part)
                    if body:
                        break
        
        return body
    
    def _extract_attachments(self, payload: Dict) -> List[Dict]:
        """Extract attachment metadata from payload."""
        attachments = []
        
        for part in payload.get('parts', []):
            if part.get('filename'):
                attachments.append({
                    'filename': part['filename'],
                    'mime_type': part.get('mimeType', ''),
                    'size': part.get('body', {}).get('size', 0),
                    'attachment_id': part.get('body', {}).get('attachmentId'),
                })
            if 'parts' in part:
                attachments.extend(self._extract_attachments(part))
        
        return attachments
    
    async def list_messages(
        self,
        query: str = "",
        max_results: int = 20,
        label_ids: List[str] = None,
        include_body: bool = False,
    ) -> List[Email]:
        """
        List email messages.
        
        Args:
            query: Gmail search query (e.g., "from:alice@example.com is:unread")
            max_results: Maximum number of results
            label_ids: Filter by label IDs (e.g., ['INBOX', 'UNREAD'])
            include_body: Whether to fetch full email body
        
        Returns:
            List of Email objects
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        try:
            # List message IDs
            request = self._service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results,
                labelIds=label_ids or [],
            )
            result = await asyncio.to_thread(request.execute)
            
            messages = result.get('messages', [])
            if not messages:
                return []
            
            # Fetch full messages
            emails = []
            for msg_info in messages:
                request = self._service.users().messages().get(
                    userId='me',
                    id=msg_info['id'],
                    format='full' if include_body else 'metadata',
                    metadataHeaders=['From', 'To', 'Subject', 'Date'],
                )
                msg = await asyncio.to_thread(request.execute)
                emails.append(self._parse_message(msg, include_body=include_body))
            
            return emails
            
        except HttpError as e:
            raise RuntimeError(f"Gmail API error: {e}")
    
    async def get_message(self, message_id: str) -> Email:
        """
        Get a single email by ID.
        
        Args:
            message_id: The message ID
        
        Returns:
            Email object with full body
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.users().messages().get(
            userId='me',
            id=message_id,
            format='full',
        )
        msg = await asyncio.to_thread(request.execute)
        return self._parse_message(msg, include_body=True)
    
    async def search(self, query: str, max_results: int = 20) -> List[Email]:
        """
        Search emails using Gmail query syntax.
        
        Examples:
            "from:alice@example.com"
            "subject:meeting is:unread"
            "has:attachment filename:pdf"
            "after:2024/01/01 before:2024/02/01"
        """
        return await self.list_messages(query=query, max_results=max_results)
    
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: str = None,
        bcc: str = None,
        html: bool = False,
        attachments: List[str] = None,
    ) -> Dict:
        """
        Send an email.
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (text or HTML)
            cc: CC recipients (comma-separated)
            bcc: BCC recipients (comma-separated)
            html: Whether body is HTML
            attachments: List of file paths to attach
        
        Returns:
            Dict with message ID and thread ID
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Create message
        if attachments:
            message = MIMEMultipart()
            message.attach(MIMEText(body, 'html' if html else 'plain'))
            
            # Add attachments
            for filepath in attachments:
                path = Path(filepath).expanduser()
                if path.exists():
                    with open(path, 'rb') as f:
                        part = MIMEBase('application', 'octet-stream')
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename="{path.name}"'
                    )
                    message.attach(part)
        else:
            message = MIMEText(body, 'html' if html else 'plain')
        
        message['to'] = to
        message['subject'] = subject
        if self._user_email:
            message['from'] = self._user_email
        if cc:
            message['cc'] = cc
        if bcc:
            message['bcc'] = bcc
        
        # Encode
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        # Send
        try:
            request = self._service.users().messages().send(
                userId='me',
                body={'raw': raw}
            )
            result = await asyncio.to_thread(request.execute)
            
            return {
                'id': result['id'],
                'thread_id': result.get('threadId'),
                'success': True,
            }
        except HttpError as e:
            raise RuntimeError(f"Failed to send email: {e}")
    
    async def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
    ) -> Dict:
        """
        Create a draft email.
        
        Returns:
            Dict with draft ID
        """
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        message = MIMEText(body, 'html' if html else 'plain')
        message['to'] = to
        message['subject'] = subject
        if self._user_email:
            message['from'] = self._user_email
        
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        try:
            request = self._service.users().drafts().create(
                userId='me',
                body={'message': {'raw': raw}}
            )
            result = await asyncio.to_thread(request.execute)
            
            return {
                'id': result['id'],
                'message_id': result.get('message', {}).get('id'),
                'success': True,
            }
        except HttpError as e:
            raise RuntimeError(f"Failed to create draft: {e}")
    
    async def get_labels(self) -> List[Dict]:
        """Get all labels (folders)."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.users().labels().list(userId='me')
        result = await asyncio.to_thread(request.execute)
        
        return [
            {'id': l['id'], 'name': l['name'], 'type': l.get('type')}
            for l in result.get('labels', [])
        ]
    
    async def mark_read(self, message_id: str):
        """Mark a message as read."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['UNREAD']}
        )
        await asyncio.to_thread(request.execute)
    
    async def mark_unread(self, message_id: str):
        """Mark a message as unread."""
        if not self._service:
            raise RuntimeError("Not connected. Call connect() first.")
        
        request = self._service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'addLabelIds': ['UNREAD']}
        )
        await asyncio.to_thread(request.execute)
